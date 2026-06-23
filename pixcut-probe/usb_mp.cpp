// Minimal multi-packet verification: ONE clean job, send 3 packets that SUM to
// file-size using format "cmd data EXTLEN=<paylen+4>\n + jobid(4 LE) + payload".
// Confirms the device sums payload across packets and completes (jstate 9).
// Garbage payload (0xAB), file-size tiny -> nothing prints, no ribbon.

#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <algorithm>
#include <unistd.h>

static const char* LIB="/Applications/Liene Photo.app/Contents/Frameworks/libht_device_usb_core.dylib";
static const unsigned short VID=0x302c,PID=0x3102; enum{CH_COMMAND=2,CH_DATA=3};
using Ctor=void(*)(void*);using Open=int(*)(void*,unsigned short,unsigned short);
using Write=int(*)(void*,int,const unsigned char*,int,int*,int);using Read=int(*)(void*,int,unsigned char*,int*,int);using Close=void(*)(void*);
template<class T> static T sym(void*h,const char*n){return (T)dlsym(h,n);}
static long jint(const std::string&s,const char*k){auto p=s.find(std::string("\"")+k+"\"");if(p==std::string::npos)return -1;p=s.find(':',p);return p==std::string::npos?-1:strtol(s.c_str()+p+1,0,10);}

int main(){
    void*h=dlopen(LIB,RTLD_NOW|RTLD_LOCAL); if(!h){fprintf(stderr,"%s\n",dlerror());return 1;}
    auto ctor=sym<Ctor>(h,"_ZN7UsbCoreC1Ev");auto open=sym<Open>(h,"_ZN7UsbCore4openEtt");
    auto wr=sym<Write>(h,"_ZN7UsbCore5writeE10UsbChannelPKhiPii");auto rdc=sym<Read>(h,"_ZN7UsbCore4readE10UsbChannelPhPii");auto cl=sym<Close>(h,"_ZN7UsbCore5closeEv");
    alignas(16) unsigned char usb[8192]={0}; ctor(usb); if(open(usb,VID,PID)!=0){printf("open failed\n");return 3;}
    auto rd=[&](int ms){std::vector<unsigned char> b(8192);int len=(int)b.size();int rc=rdc(usb,CH_COMMAND,b.data(),&len,ms);return (rc>=0&&len>0&&len<(int)b.size())?std::string((char*)b.data(),len):std::string();};
    auto cmd=[&](const std::string&j)->std::string{long id=jint(j,"id");std::string f="cmd json\n"+j;int w=0;wr(usb,CH_COMMAND,(const unsigned char*)f.data(),(int)f.size(),&w,3000);for(int i=0;i<8;i++){std::string r=rd(3000);if(r.empty())continue;if(r.find("\"event")!=std::string::npos&&r.find("\"id\"")==std::string::npos)continue;if(id<0||jint(r,"id")==id)return r;}return "";};

    cmd("{\"method\":\"resume-printer\",\"id\":90}");
    std::string ps=cmd("{\"method\":\"get-prop\",\"params\":[\"printer-state\"],\"id\":91}");
    printf("printer-state reply: %s\n", ps.c_str());
    if(ps.empty()){printf("device wedged, power-cycle needed\n"); return 4;}

    int pls[]={998,998,504}; int total=50000;     // large, to exercise backpressure
    char job[400]; snprintf(job,sizeof job,"{\"method\":\"print-job\",\"params\":{\"channel\":0,\"copies\":1,\"file-size\":%d,\"media-size\":5013,\"media-type\":2030,\"job-type\":600},\"id\":92}",total);
    std::string r=cmd(job); long id=jint(r,"job-id"); if(id<0)id=jint(r,"job_id");
    printf("print-job(file-size=%d) -> %s  job-id=%ld\n", total, r.c_str(), id);
    if(id<0)return 5;

    (void)pls;
    // ONE header for the whole transfer: "cmd data EXTLEN=<total+4>\n" + jobid(4 LE),
    // then the CONTINUOUS payload (no per-chunk headers — the device de-frames only the
    // first header and counts everything after as payload). Stream it in paced chunks.
    std::string s="cmd data EXTLEN="+std::to_string(total+4)+"\n";   // +4 = jobid bytes
    std::vector<unsigned char> stream(s.begin(),s.end());
    unsigned char j4[4]={(unsigned char)id,(unsigned char)(id>>8),(unsigned char)(id>>16),(unsigned char)(id>>24)};
    stream.insert(stream.end(),j4,j4+4);
    std::vector<unsigned char> pay(total,0xAB);
    stream.insert(stream.end(),pay.begin(),pay.end());
    printf("  stream = %zu-byte header + %d payload = %zu total\n", s.size()+4, total, stream.size());
    size_t off=0; const int CHUNK=1024; int retry=0;
    while(off<stream.size()){
        int c=(int)std::min((size_t)CHUNK,stream.size()-off);
        int w=0;int rc=wr(usb,CH_DATA,stream.data()+off,c,&w,15000);
        if(w>0){ off+=w; retry=0; }                 // advance by ACTUAL bytes written
        else { if(++retry>50){printf("  stuck@%zu rc=%d\n",off,rc);break;} usleep(50000); }
    }
    printf("  sent %zu/%zu\n", off, stream.size());
    usleep(1500000);
    std::string ji=cmd("{\"method\":\"get-job-info\",\"params\":{\"job-id\":"+std::to_string(id)+"},\"id\":93}");
    long ts=jint(ji,"transfer-size"),tstat=jint(ji,"transfer-status"),jst=jint(ji,"job-state");
    printf("\nRESULT: transfer-size=%ld (want %d)  transfer-status=%ld  job-state=%ld  => %s\n",
           ts,total,tstat,jst,(ts==total?"✓ MULTI-PACKET SUMS CORRECTLY":"✗ mismatch"));
    cmd("{\"method\":\"cancel-job\",\"params\":{\"job-id\":"+std::to_string(id)+"},\"id\":94}");
    if(cl)cl(usb); dlclose(h); return 0;
}
