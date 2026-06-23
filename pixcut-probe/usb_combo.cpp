// Combo print+cut to the PixCut S1 over USB — reproduces the app's combo-job:
//   combo-job[ print-job{file-size=jpegLen}, cut-job{file-size=pltLen} ]
//   then streams (jpeg ++ plt) as cmd data packets on the Data channel.
//
// SAFETY: dry-run by default. Pass "GO" to actually print+cut (consumes paper+ribbon).
//
// Build: clang++ -std=c++17 -arch arm64 usb_combo.cpp -o usb_combo \
//          -Wl,-rpath,"/Applications/Liene Photo.app/Contents/Frameworks"
// Run:   ./usb_combo [GO] [jpeg] [plt]
//   defaults: samples/sample_4x7.jpg + samples/sample_4x7_cut.plt (exact app repro)

#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <algorithm>
#include <unistd.h>

static const char* LIB =
    "/Applications/Liene Photo.app/Contents/Frameworks/libht_device_usb_core.dylib";
static const unsigned short VID = 0x302c, PID = 0x3102;
enum { CH_COMMAND = 2, CH_DATA = 3 };
static const int PAYLOAD = 998;                 // app's effective payload over USB
static const int MEDIA_SIZE = 5013, MEDIA_TYPE = 2030, JOB_TYPE = 600;  // 4x7, from real log

static const char* D_JPG = "/Users/xiaomengen/work/vscode/heyou/pixcut-probe/samples/sample_4x7.jpg";
static const char* D_PLT = "/Users/xiaomengen/work/vscode/heyou/pixcut-probe/samples/sample_4x7_cut.plt";

using Ctor=void(*)(void*); using Open=int(*)(void*,unsigned short,unsigned short);
using Write=int(*)(void*,int,const unsigned char*,int,int*,int);
using Read=int(*)(void*,int,unsigned char*,int*,int); using Close=void(*)(void*);
template<class T> static T sym(void*h,const char*n){T p=(T)dlsym(h,n);if(!p)fprintf(stderr,"MISSING %s\n",n);return p;}

static std::vector<unsigned char> rd(const char* p){
    FILE*f=fopen(p,"rb"); if(!f){fprintf(stderr,"open %s failed\n",p);return{};}
    fseek(f,0,SEEK_END); long n=ftell(f); fseek(f,0,SEEK_SET);
    std::vector<unsigned char> b(n); if(fread(b.data(),1,n,f)!=(size_t)n)b.clear(); fclose(f); return b;
}
static long jint(const std::string&s,const char*k){auto p=s.find(std::string("\"")+k+"\"");if(p==std::string::npos)return -1;p=s.find(':',p);return p==std::string::npos?-1:strtol(s.c_str()+p+1,0,10);}

int main(int argc,char**argv){
    bool go=(argc>1&&std::string(argv[1])=="GO");
    const char* jp=(argc>2)?argv[2]:D_JPG;
    const char* pp=(argc>3)?argv[3]:D_PLT;

    auto jpeg=rd(jp), plt=rd(pp);
    if(jpeg.empty()||plt.empty())return 1;
    bool okJ=jpeg.size()>2&&jpeg[0]==0xFF&&jpeg[1]==0xD8;
    bool okP=plt.size()>3&&memcmp(plt.data(),"IN ",3)==0;
    printf("jpeg: %s (%zu bytes, %s)\n", jp, jpeg.size(), okJ?"JPEG ok":"NOT JPEG");
    printf("plt : %s (%zu bytes, %s)\n", pp, plt.size(), okP?"PLT ok":"NOT PLT");

    // data stream = jpeg ++ plt
    std::vector<unsigned char> data=jpeg; data.insert(data.end(),plt.begin(),plt.end());
    int nPk=(int)((data.size()+PAYLOAD-1)/PAYLOAD);

    char cmd[640];
    snprintf(cmd,sizeof cmd,
      "{\"method\":\"combo-job\",\"params\":["
      "{\"method\":\"print-job\",\"params\":{\"channel\":0,\"copies\":1,\"file-size\":%zu,"
      "\"media-size\":%d,\"media-type\":%d,\"job-type\":%d}},"
      "{\"method\":\"cut-job\",\"params\":{\"file-size\":%zu,\"job-type\":%d}}],\"id\":2}",
      jpeg.size(),MEDIA_SIZE,MEDIA_TYPE,JOB_TYPE,plt.size(),JOB_TYPE);

    printf("\n--- PLAN ---\ncombo-job: %s\n", cmd);
    printf("data stream: %zu (jpeg %zu + plt %zu) over %d packets <=%d payload on ch %d\n",
           data.size(),jpeg.size(),plt.size(),nPk,PAYLOAD,CH_DATA);

    void*h=dlopen(LIB,RTLD_NOW|RTLD_LOCAL); if(!h){fprintf(stderr,"%s\n",dlerror());return 1;}
    auto ctor=sym<Ctor>(h,"_ZN7UsbCoreC1Ev");auto open=sym<Open>(h,"_ZN7UsbCore4openEtt");
    auto wr=sym<Write>(h,"_ZN7UsbCore5writeE10UsbChannelPKhiPii");
    auto rdc=sym<Read>(h,"_ZN7UsbCore4readE10UsbChannelPhPii");auto cl=sym<Close>(h,"_ZN7UsbCore5closeEv");
    if(!ctor||!open||!wr||!rdc)return 2;
    alignas(16) unsigned char usb[8192]={0}; ctor(usb);
    if(open(usb,VID,PID)!=0){printf("open failed\n");return 3;}
    printf("device opened\n");

    auto readMsg=[&](int timeoutMs)->std::string{
        std::vector<unsigned char> b(8192);int len=(int)b.size();
        int rc=rdc(usb,CH_COMMAND,b.data(),&len,timeoutMs);
        return (rc>=0&&len>0&&len<(int)b.size())?std::string((char*)b.data(),len):"";
    };
    // Drain any pending async events (e.g. a previous job's timeout) before starting.
    for(int i=0;i<5;i++){std::string e=readMsg(300); if(e.empty())break; printf("  [drain] %s\n",e.c_str());}

    // Send a command and read until the reply with OUR id arrives, skipping
    // async "event.*" pushes and stale/mismatched messages.
    auto sendCmd=[&](const std::string&j)->std::string{
        long myId=jint(j,"id");
        std::string f="cmd json\n"+j; int w=0;
        wr(usb,CH_COMMAND,(const unsigned char*)f.data(),(int)f.size(),&w,3000);
        for(int i=0;i<8;i++){
            std::string r=readMsg(3000); if(r.empty())continue;
            if(r.find("\"event")!=std::string::npos && r.find("\"id\"")==std::string::npos){
                printf("  [event] %s\n", r.c_str()); continue; }
            if(myId<0 || jint(r,"id")==myId) return r;
            printf("  [skip mismatched] %s\n", r.c_str());
        }
        return "";
    };

    std::string st=sendCmd("{\"method\":\"get-prop\",\"params\":[\"media-size\",\"printer-state\"],\"id\":1}");
    printf("device now reports: %s\n", st.c_str());

    if(!go){ printf("\n[DRY RUN] not sending. Re-run with GO to print+cut.\n"); if(cl)cl(usb); return 0; }

    // Clear any leftover/stuck job state so we don't need a manual power-cycle.
    std::string rp=sendCmd("{\"method\":\"resume-printer\",\"id\":9}");
    printf("resume-printer: %s\n", rp.c_str());

    printf("\n[GO] creating combo job ...\n");
    std::string resp=sendCmd(cmd); printf("combo-job reply: %s\n", resp.c_str());
    long jobId=jint(resp,"job-id"); if(jobId<0)jobId=jint(resp,"job_id");
    if(jobId<0){printf("no job-id, abort\n"); if(cl)cl(usb); return 4;}
    printf("job-id=%ld; streaming %zu bytes ...\n", jobId, data.size());

    // Per-packet framing matching the app (effectivePayload=998, maxPacket=1024,
    // header=26): each packet = "cmd data EXTLEN=<pktsize>\n"(21, 4-digit) + jobid(4 LE)
    // + 1 pad byte = 26-byte header, then payload (= pktsize-26). The device strips the
    // 26-byte header per packet and counts only payload -> transfer-size should == 208578.
    // CONFIRMED framing: ONE "cmd data EXTLEN=<payload+4>\n" + jobid(4 LE) header for the
    // whole transfer, then the CONTINUOUS payload (jpeg ++ plt). The device de-frames only
    // this one header and counts everything after as payload. Stream in ~1KB chunks paced
    // ~60KB/s (the app's rate) to avoid overflowing the device's receive buffer; retry on
    // NAK/timeout (device applies backpressure as it drains).
    unsigned char jb[4]={(unsigned char)jobId,(unsigned char)(jobId>>8),(unsigned char)(jobId>>16),(unsigned char)(jobId>>24)};
    std::string hdr="cmd data EXTLEN="+std::to_string(data.size()+4)+"\n";
    std::vector<unsigned char> stream(hdr.begin(),hdr.end());
    stream.insert(stream.end(),jb,jb+4);
    stream.insert(stream.end(),data.begin(),data.end());
    printf("stream: %zu-byte header + %zu payload = %zu (EXTLEN=%zu)\n",
           hdr.size()+4, data.size(), stream.size(), data.size()+4);
    // Advance by ACTUAL bytes written (w). On backpressure UsbCore::write may write
    // partial or 0; advancing by w (not the requested chunk) avoids re-sending already-
    // accepted bytes (which corrupts the stream — that froze the earlier attempt at 3973).
    // Pace to the app's rate (~17ms per 1KB ≈ 60KB/s) so the device prints/drains its
    // ~96KB receive buffer as fast as we fill it (blasting overflows it -> pipe STALL -203).
    size_t off=0; const int CHUNK=1024, PACE_US=17000; int retry=0;
    while(off<stream.size()){
        int c=(int)std::min((size_t)CHUNK,stream.size()-off);
        int w=0;int rc=wr(usb,CH_DATA,stream.data()+off,c,&w,15000);
        if(w>0){ off+=w; retry=0; usleep(PACE_US); }
        else { if(++retry>80){printf("stuck@%zu rc=%d, abort\n",off,rc); if(cl)cl(usb); return 5;} usleep(60000); }
        if(off%40000<CHUNK) printf("  %zu/%zu bytes\n",off,stream.size());
    }
    printf("data done: %zu bytes\n", off);
    for(int i=0;i<10;i++){
        std::string ji=sendCmd("{\"method\":\"get-job-info\",\"params\":{\"job-id\":"+std::to_string(jobId)+"},\"id\":3}");
        printf("  job-info: %s\n", ji.c_str()); sleep(3);
    }
    if(cl)cl(usb); dlclose(h); return 0;
}
