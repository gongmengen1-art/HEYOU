// Disciplined data-packet HEADER reverse-engineering for the PixCut S1 over USB.
// Oracle = transfer-size in get-job-info. For each candidate header format we:
//   resume-printer -> create print-job(file-size=PAYLEN) -> get job-id ->
//   send ONE data packet (candidate header + PAYLEN payload) -> read transfer-size ->
//   cancel-job. The format whose transfer-size == PAYLEN de-framed correctly.
//
// PAYLEN is an irregular number (777) so the delta (transfer-size - PAYLEN) tells us
// exactly how many header bytes the device mis-counted.
//
// Nothing prints (file-size=777 of 0xAB is not a valid image, and we cancel each job),
// so no ribbon is consumed.
//
// Build: clang++ -std=c++17 -arch arm64 usb_probe.cpp -o usb_probe \
//          -Wl,-rpath,"/Applications/Liene Photo.app/Contents/Frameworks"

#include <dlfcn.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <functional>
#include <unistd.h>

static const char* LIB =
    "/Applications/Liene Photo.app/Contents/Frameworks/libht_device_usb_core.dylib";
static const unsigned short VID = 0x302c, PID = 0x3102;
enum { CH_COMMAND = 2, CH_DATA = 3 };
static const int MEDIA_SIZE = 5013, MEDIA_TYPE = 2030, JOB_TYPE = 600;
static const int PAYLEN = 777;                 // irregular -> deltas are diagnostic

using Ctor=void(*)(void*); using Open=int(*)(void*,unsigned short,unsigned short);
using Write=int(*)(void*,int,const unsigned char*,int,int*,int);
using Read=int(*)(void*,int,unsigned char*,int*,int); using Close=void(*)(void*);
template<class T> static T sym(void*h,const char*n){T p=(T)dlsym(h,n);if(!p)fprintf(stderr,"MISSING %s\n",n);return p;}

static long jint(const std::string&s,const char*k){
    auto p=s.find(std::string("\"")+k+"\""); if(p==std::string::npos)return -1;
    p=s.find(':',p); if(p==std::string::npos)return -1; return strtol(s.c_str()+p+1,0,10);
}

int main(){
    void* h=dlopen(LIB,RTLD_NOW|RTLD_LOCAL); if(!h){fprintf(stderr,"%s\n",dlerror());return 1;}
    auto ctor=sym<Ctor>(h,"_ZN7UsbCoreC1Ev");auto open=sym<Open>(h,"_ZN7UsbCore4openEtt");
    auto wr=sym<Write>(h,"_ZN7UsbCore5writeE10UsbChannelPKhiPii");
    auto rdc=sym<Read>(h,"_ZN7UsbCore4readE10UsbChannelPhPii");auto cl=sym<Close>(h,"_ZN7UsbCore5closeEv");
    if(!ctor||!open||!wr||!rdc)return 2;
    alignas(16) unsigned char usb[8192]={0}; ctor(usb);
    if(open(usb,VID,PID)!=0){printf("open failed\n");return 3;}

    auto readMsg=[&](int ms)->std::string{
        std::vector<unsigned char> b(8192);int len=(int)b.size();
        int rc=rdc(usb,CH_COMMAND,b.data(),&len,ms);
        return (rc>=0&&len>0&&len<(int)b.size())?std::string((char*)b.data(),len):"";
    };
    auto sendCmd=[&](const std::string&j)->std::string{
        long myId=jint(j,"id"); std::string f="cmd json\n"+j; int w=0;
        wr(usb,CH_COMMAND,(const unsigned char*)f.data(),(int)f.size(),&w,3000);
        for(int i=0;i<8;i++){
            std::string r=readMsg(3000); if(r.empty())continue;
            if(r.find("\"event")!=std::string::npos&&r.find("\"id\"")==std::string::npos)continue;
            if(myId<0||jint(r,"id")==myId)return r;
        }
        return "";
    };

    unsigned char payload[PAYLEN]; memset(payload,0xAB,sizeof payload);
    unsigned char jb[4];

    // Each format builds the per-packet header (NOT incl. payload). pkt = header+payload.
    struct Fmt { const char* name; std::function<std::vector<unsigned char>(unsigned)> hdr; };
    std::vector<Fmt> fmts = {
      {"F1 EXTLEN=paylen + jobid(4)", [&](unsigned id){
          std::string s="cmd data EXTLEN="+std::to_string(PAYLEN)+"\n"; std::vector<unsigned char> v(s.begin(),s.end());
          jb[0]=id;jb[1]=id>>8;jb[2]=id>>16;jb[3]=id>>24; v.insert(v.end(),jb,jb+4); return v; }},
      {"F2 EXTLEN=paylen, no jobid", [&](unsigned){
          std::string s="cmd data EXTLEN="+std::to_string(PAYLEN)+"\n"; return std::vector<unsigned char>(s.begin(),s.end()); }},
      {"F3 EXTLEN=paylen + jobid(4) + pad(1)", [&](unsigned id){
          std::string s="cmd data EXTLEN="+std::to_string(PAYLEN)+"\n"; std::vector<unsigned char> v(s.begin(),s.end());
          jb[0]=id;jb[1]=id>>8;jb[2]=id>>16;jb[3]=id>>24; v.insert(v.end(),jb,jb+4); v.push_back(0); return v; }},
      {"F4 EXTLEN=pktsize(paylen+jobid) + jobid(4)", [&](unsigned id){
          std::string s="cmd data EXTLEN="+std::to_string(PAYLEN+4)+"\n"; std::vector<unsigned char> v(s.begin(),s.end());
          jb[0]=id;jb[1]=id>>8;jb[2]=id>>16;jb[3]=id>>24; v.insert(v.end(),jb,jb+4); return v; }},
      {"F5 EXTLEN=1024 fixed + jobid(4) + pad(1)", [&](unsigned id){
          std::string s="cmd data EXTLEN=1024\n"; std::vector<unsigned char> v(s.begin(),s.end());
          jb[0]=id;jb[1]=id>>8;jb[2]=id>>16;jb[3]=id>>24; v.insert(v.end(),jb,jb+4); v.push_back(0); return v; }},
    };

    printf("PAYLEN=%d (want transfer-size==%d). delta = device over/under-count.\n\n", PAYLEN, PAYLEN);
    for(auto& fmt : fmts){
        sendCmd("{\"method\":\"resume-printer\",\"id\":90}");
        // verify device responsive
        std::string ps=sendCmd("{\"method\":\"get-prop\",\"params\":[\"printer-state\"],\"id\":91}");
        if(ps.empty()){ printf("%-44s DEVICE UNRESPONSIVE (wedged) — power-cycle needed, stopping.\n", fmt.name); break; }

        char job[400]; snprintf(job,sizeof job,
          "{\"method\":\"print-job\",\"params\":{\"channel\":0,\"copies\":1,\"file-size\":%d,"
          "\"media-size\":%d,\"media-type\":%d,\"job-type\":%d},\"id\":92}",
          PAYLEN,MEDIA_SIZE,MEDIA_TYPE,JOB_TYPE);
        std::string r=sendCmd(job);
        long id=jint(r,"job-id"); if(id<0)id=jint(r,"job_id");
        if(id<0){ printf("%-44s no job-id (reply='%s')\n", fmt.name, r.c_str()); continue; }

        std::vector<unsigned char> fr=fmt.hdr((unsigned)id);
        int hdrlen=(int)fr.size();
        fr.insert(fr.end(),payload,payload+PAYLEN);
        int w=0; int wrc=wr(usb,CH_DATA,fr.data(),(int)fr.size(),&w,5000);
        usleep(800000);
        std::string ji=sendCmd("{\"method\":\"get-job-info\",\"params\":{\"job-id\":"+std::to_string(id)+"},\"id\":93}");
        long ts=jint(ji,"transfer-size"), tstat=jint(ji,"transfer-status"), jst=jint(ji,"job-state");
        long delta = (ts<0)? -999999 : ts-PAYLEN;
        printf("%-44s job=%ld hdr=%dB wrc=%d w=%d | transfer-size=%ld (delta %+ld) tstat=%ld jstate=%ld\n",
               fmt.name, id, hdrlen, wrc, w, ts, delta, tstat, jst);
        sendCmd("{\"method\":\"cancel-job\",\"params\":{\"job-id\":"+std::to_string(id)+"},\"id\":94}");
        usleep(300000);
    }

    // ---- Multi-packet verification of the winning format (F4: EXTLEN=payload+4) ----
    printf("\n=== multi-packet F4 verify (EXTLEN=payload+4 per packet) ===\n");
    {
        sendCmd("{\"method\":\"resume-printer\",\"id\":90}");
        std::string ps=sendCmd("{\"method\":\"get-prop\",\"params\":[\"printer-state\"],\"id\":91}");
        if(ps.empty()){ printf("device wedged, skip\n"); }
        else {
            int paylens[]={998,998,504}; int total=998+998+504;   // 2500
            char job[400]; snprintf(job,sizeof job,
              "{\"method\":\"print-job\",\"params\":{\"channel\":0,\"copies\":1,\"file-size\":%d,"
              "\"media-size\":%d,\"media-type\":%d,\"job-type\":%d},\"id\":92}",
              total,MEDIA_SIZE,MEDIA_TYPE,JOB_TYPE);
            std::string r=sendCmd(job); long id=jint(r,"job-id"); if(id<0)id=jint(r,"job_id");
            if(id<0){ printf("no job-id (reply='%s')\n", r.c_str()); }
            else {
                std::vector<unsigned char> bigpay(total,0xAB);
                size_t off=0;
                for(int pl : paylens){
                    std::string s="cmd data EXTLEN="+std::to_string(pl+4)+"\n";
                    std::vector<unsigned char> fr(s.begin(),s.end());
                    unsigned char j4[4]={(unsigned char)id,(unsigned char)(id>>8),(unsigned char)(id>>16),(unsigned char)(id>>24)};
                    fr.insert(fr.end(),j4,j4+4);
                    fr.insert(fr.end(),bigpay.begin()+off,bigpay.begin()+off+pl);
                    int w=0; wr(usb,CH_DATA,fr.data(),(int)fr.size(),&w,5000); off+=pl; usleep(20000);
                }
                usleep(800000);
                std::string ji=sendCmd("{\"method\":\"get-job-info\",\"params\":{\"job-id\":"+std::to_string(id)+"},\"id\":93}");
                long ts=jint(ji,"transfer-size"),tstat=jint(ji,"transfer-status"),jst=jint(ji,"job-state");
                printf("3 packets, total payload=%d -> transfer-size=%ld (want %d) tstat=%ld jstate=%ld %s\n",
                       total,ts,total,tstat,jst, (ts==total?"✓ SUMS CORRECTLY":"✗"));
                sendCmd("{\"method\":\"cancel-job\",\"params\":{\"job-id\":"+std::to_string(id)+"},\"id\":94}");
            }
        }
    }

    if(cl)cl(usb); dlclose(h); return 0;
}
