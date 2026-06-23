// Plain print (no cut) of a JPEG to the PixCut S1 over USB, using the app's
// own libht_device_usb_core.dylib UsbCore transport + the reverse-engineered
// cmd json / cmd data framing.
//
// SAFETY: dry-run by default (queries device, prints the plan, sends NOTHING
// that starts a print). Pass "GO" as argv[1] to actually create the job and
// stream the image (consumes paper + ribbon).
//
// Build: clang++ -std=c++17 -arch arm64 usb_print.cpp -o usb_print \
//          -Wl,-rpath,"/Applications/Liene Photo.app/Contents/Frameworks"
// Run:   ./usb_print            (dry run)
//        ./usb_print GO [img]   (real print; img defaults to samples/sample_4x7.jpg)

#include <dlfcn.h>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include <algorithm>
#include <unistd.h>

static const char* LIB =
    "/Applications/Liene Photo.app/Contents/Frameworks/libht_device_usb_core.dylib";
static const unsigned short VID = 0x302c, PID = 0x3102;
enum { CH_COMMAND = 2, CH_DATA = 3 };

static const char* DEFAULT_IMG =
    "/Users/xiaomengen/work/vscode/heyou/pixcut-probe/samples/sample_4x7.jpg";

// job-type / document-format observed from the app's real combo-job. media-size
// / media-type are read live from the device (depend on loaded paper).
static const int JOB_TYPE = 600;
static const int MAX_PKT = 1024, PAYLOAD = 998;   // USB framing the app uses

using Ctor  = void (*)(void*);
using Open  = int  (*)(void*, unsigned short, unsigned short);
using Write = int  (*)(void*, int, const unsigned char*, int, int*, int);
using Read  = int  (*)(void*, int, unsigned char*, int*, int);
using Close = void (*)(void*);

template <class T> static T sym(void* h, const char* n) {
    T p = (T)dlsym(h, n); if (!p) fprintf(stderr, "MISSING SYMBOL %s\n", n); return p;
}

static std::vector<unsigned char> readFile(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "cannot open %s\n", path); return {}; }
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    std::vector<unsigned char> b(n);
    if (fread(b.data(), 1, n, f) != (size_t)n) b.clear();
    fclose(f); return b;
}

// extract integer value of "key": from a JSON-ish string
static long jsonInt(const std::string& s, const std::string& key, long dflt) {
    auto p = s.find("\"" + key + "\"");
    if (p == std::string::npos) return dflt;
    p = s.find(':', p); if (p == std::string::npos) return dflt;
    return strtol(s.c_str() + p + 1, nullptr, 10);
}

int main(int argc, char** argv) {
    bool go = (argc > 1 && std::string(argv[1]) == "GO");
    const char* img = (argc > 2) ? argv[2] : DEFAULT_IMG;

    auto jpeg = readFile(img);
    if (jpeg.empty()) return 1;
    bool isJpeg = jpeg.size() > 2 && jpeg[0] == 0xFF && jpeg[1] == 0xD8;
    printf("image: %s  (%zu bytes, %s)\n", img, jpeg.size(), isJpeg ? "JPEG ok" : "NOT JPEG?!");

    void* h = dlopen(LIB, RTLD_NOW | RTLD_LOCAL);
    if (!h) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
    auto ctor=sym<Ctor>(h,"_ZN7UsbCoreC1Ev"); auto open=sym<Open>(h,"_ZN7UsbCore4openEtt");
    auto write=sym<Write>(h,"_ZN7UsbCore5writeE10UsbChannelPKhiPii");
    auto read=sym<Read>(h,"_ZN7UsbCore4readE10UsbChannelPhPii");
    auto close=sym<Close>(h,"_ZN7UsbCore5closeEv");
    if (!ctor||!open||!write||!read) return 2;

    alignas(16) unsigned char usb[8192] = {0};
    ctor(usb);
    if (open(usb, VID, PID) != 0) { printf("open failed\n"); return 3; }
    printf("device opened\n");

    auto sendCmd = [&](const std::string& json) -> std::string {
        std::string frame = "cmd json\n" + json;
        int w = 0;
        write(usb, CH_COMMAND, (const unsigned char*)frame.data(), (int)frame.size(), &w, 3000);
        std::vector<unsigned char> buf(8192); int len = (int)buf.size();
        int rc = read(usb, CH_COMMAND, buf.data(), &len, 3000);
        if (rc >= 0 && len > 0 && len < (int)buf.size()) return std::string((char*)buf.data(), len);
        return "";
    };

    // Read live media-size / media-type for the loaded paper.
    std::string st = sendCmd("{\"method\":\"get-prop\",\"params\":[\"media-size\",\"media-type\",\"printer-state\"],\"id\":1}");
    printf("device get-prop reply: %s\n", st.c_str());
    long mediaSize = jsonInt(st, "media-size", 5013);
    long mediaType = jsonInt(st, "media-type", 2030);

    // Build the print-job command (plain print, no cut).
    char job[512];
    snprintf(job, sizeof job,
        "{\"method\":\"print-job\",\"params\":{\"channel\":0,\"copies\":1,"
        "\"file-size\":%zu,\"media-size\":%ld,\"media-type\":%ld,\"job-type\":%d},\"id\":2}",
        jpeg.size(), mediaSize, mediaType, JOB_TYPE);

    int nPackets = (int)((jpeg.size() + PAYLOAD - 1) / PAYLOAD);
    printf("\n--- PLAN ---\n");
    printf("media-size=%ld media-type=%ld job-type=%d\n", mediaSize, mediaType, JOB_TYPE);
    printf("print-job cmd: %s\n", job);
    printf("data: %zu bytes over %d packets of <=%d payload on Data channel (%d)\n",
           jpeg.size(), nPackets, PAYLOAD, CH_DATA);

    if (!go) {
        printf("\n[DRY RUN] not sending. Re-run with: ./usb_print GO  to actually print.\n");
        if (close) close(usb); dlclose(h); return 0;
    }

    // ---- REAL PRINT ----
    printf("\n[GO] creating job ...\n");
    std::string resp = sendCmd(job);
    printf("print-job reply: %s\n", resp.c_str());
    long jobId = jsonInt(resp, "job-id", -1);
    if (jobId < 0) { printf("no job-id in reply, aborting\n"); if (close) close(usb); return 4; }
    printf("job-id=%ld; streaming image on Data channel ...\n", jobId);

    unsigned char jb[4] = { (unsigned char)(jobId), (unsigned char)(jobId>>8),
                            (unsigned char)(jobId>>16), (unsigned char)(jobId>>24) };
    size_t off = 0; int pkt = 0, failed = 0;
    while (off < jpeg.size()) {
        int chunk = (int)std::min((size_t)PAYLOAD, jpeg.size() - off);
        std::string hdr = "cmd data EXTLEN=" + std::to_string(chunk) + "\n";
        std::vector<unsigned char> frame;
        frame.insert(frame.end(), hdr.begin(), hdr.end());
        frame.insert(frame.end(), jb, jb + 4);
        frame.insert(frame.end(), jpeg.begin() + off, jpeg.begin() + off + chunk);
        int w = 0;
        int rc = write(usb, CH_DATA, frame.data(), (int)frame.size(), &w, 5000);
        if (rc < 0 || w != (int)frame.size()) { failed++; if (failed > 3) { printf("write failing rc=%d, abort\n", rc); break; } }
        off += chunk; pkt++;
        if (pkt % 40 == 0) printf("  sent %d/%d packets\n", pkt, nPackets);
    }
    printf("data send done: %d packets, %zu bytes\n", pkt, off);

    // Poll job status a few times.
    for (int i = 0; i < 8; i++) {
        std::string ji = sendCmd("{\"method\":\"get-job-info\",\"params\":{\"job-id\":" + std::to_string(jobId) + "},\"id\":3}");
        printf("  job-info: %s\n", ji.c_str());
        sleep(3);
    }

    if (close) close(usb);
    dlclose(h);
    return 0;
}
