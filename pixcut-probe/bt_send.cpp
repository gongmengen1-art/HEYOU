// Plan B: talk to the PixCut S1 through the app's OWN Bluetooth transport
// (libht_device_bt_core.dylib, the bt_native::Platform* API) instead of the
// /dev/cu SPP serial mapping. This uses the exact same IOBluetooth RFCOMM path
// and async run-loop pumping the official app uses, so it hits the right
// channel with the right connection handshake.
//
// Sends ONE read-only get-prop query (no print/cut) and prints the reply.
//
// Build: clang++ -std=c++17 -arch arm64 bt_send.cpp -o bt_send \
//          -Wl,-rpath,"/Applications/Liene Photo.app/Contents/Frameworks"
// Run:   ./bt_send         (quit the official app first; allow Bluetooth if prompted)

#include <dlfcn.h>
#include <cstdio>
#include <string>
#include <vector>
#include <optional>
#include <unistd.h>
#include <CoreFoundation/CoreFoundation.h>

// Run the REAL main run loop for `secs`, draining both run-loop sources and the
// main dispatch queue. IOBluetooth's async RFCOMM open/read callbacks land on
// one of those; bt_core's own PlatformPumpRunLoop returns early when no source
// is attached to the mode it pumps, so we drive the run loop ourselves.
static void runloop(double secs) {
    CFRunLoopRunInMode(kCFRunLoopDefaultMode, secs, false);
}

static const char* LIB =
    "/Applications/Liene Photo.app/Contents/Frameworks/libht_device_bt_core.dylib";

static const char* MAC_CANDIDATES[] = { "F0:13:C1:78:9C:D0", "F0-13-C1-78-9C-D0" };

static const std::string FRAME =
    "cmd json\n"
    "{\"method\":\"get-prop\",\"params\":[\"printer-state\",\"printer-sub-state\","
    "\"printer-state-alerts\",\"media-size\",\"media-type\",\"device-info\","
    "\"firmware-version\"],\"id\":1}";

// Real C++ signatures (non-virtual free functions in namespace bt_native).
using CoreCreate  = void* (*)(std::string* err);
using Resolve     = int   (*)(const std::string& addr, std::string* outDeviceId, std::string* err);
using SessOpen    = int   (*)(void* core, const std::string& devId,
                              const std::optional<std::string>& channel,
                              std::string* outInfo, std::string* err);
using SessIsOpen  = int   (*)(void* core, const std::string& devId, bool* isOpen, std::string* err);
using SessWrite   = int   (*)(void* core, const std::string& devId,
                              const unsigned char* data, int len, int* written, std::string* err);
using SessRead    = int   (*)(void* core, const std::string& devId, int maxLen,
                              std::vector<unsigned char>* out, std::string* err);
using SessClose   = int   (*)(void* core, const std::string& devId, std::string* err);
using SvcList     = int   (*)(void* core, const std::string& devId, std::string* out, std::string* err);
using PumpRunLoop = void  (*)(int ms);

template <class T> static T sym(void* h, const char* n) {
    T p = (T)dlsym(h, n);
    if (!p) fprintf(stderr, "MISSING SYMBOL: %s\n", n);
    return p;
}

static void hexdump(const unsigned char* p, size_t n) {
    for (size_t i = 0; i < n; i += 16) {
        printf("  %04zx  ", i);
        for (size_t j = 0; j < 16; j++) {
            if (i + j < n) printf("%02x ", p[i + j]); else printf("   ");
            if (j == 7) printf(" ");
        }
        printf(" |");
        for (size_t j = 0; j < 16 && i + j < n; j++) {
            unsigned char c = p[i + j];
            printf("%c", (c >= 32 && c < 127) ? c : '.');
        }
        printf("|\n");
    }
}

int main() {
    void* h = dlopen(LIB, RTLD_NOW | RTLD_LOCAL);
    if (!h) { fprintf(stderr, "dlopen failed: %s\n", dlerror()); return 1; }

    auto create  = sym<CoreCreate>(h,  "_ZN9bt_native18PlatformCoreCreateEPNSt3__112basic_stringIcNS0_11char_traitsIcEENS0_9allocatorIcEEEE");
    auto resolve = sym<Resolve>(h,     "_ZN9bt_native37PlatformResolveClassicDeviceByAddressERKNSt3__112basic_stringIcNS0_11char_traitsIcEENS0_9allocatorIcEEEEPS6_S9_");
    auto sOpen   = sym<SessOpen>(h,    "_ZN9bt_native25PlatformRfcommSessionOpenEPNS_12PlatformCoreERKNSt3__112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEERKNS2_8optionalIS8_EEPS8_SF_");
    auto sIsOpen = sym<SessIsOpen>(h,  "_ZN9bt_native27PlatformRfcommSessionIsOpenEPNS_12PlatformCoreERKNSt3__112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEEPbPS8_");
    auto sWrite  = sym<SessWrite>(h,   "_ZN9bt_native26PlatformRfcommSessionWriteEPNS_12PlatformCoreERKNSt3__112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEEPKhiPiPS8_");
    auto sRead   = sym<SessRead>(h,    "_ZN9bt_native25PlatformRfcommSessionReadEPNS_12PlatformCoreERKNSt3__112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEEiPNS2_6vectorIhNS6_IhEEEEPS8_");
    auto sClose  = sym<SessClose>(h,   "_ZN9bt_native26PlatformRfcommSessionCloseEPNS_12PlatformCoreERKNSt3__112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEEPS8_");
    auto svcList = sym<SvcList>(h,     "_ZN9bt_native26PlatformRfcommServicesListEPNS_12PlatformCoreERKNSt3__112basic_stringIcNS2_11char_traitsIcEENS2_9allocatorIcEEEEPS8_SB_");
    auto pump    = sym<PumpRunLoop>(h, "_ZN9bt_native19PlatformPumpRunLoopEi");
    if (!create || !resolve || !sOpen || !sWrite || !sRead || !pump) return 2;

    (void)pump;  // available but unreliable; we drive CFRunLoop ourselves

    std::string err;
    void* core = create(&err);
    printf("PlatformCoreCreate -> core=%p err='%s'\n", core, err.c_str());
    if (!core) return 3;
    runloop(0.5);  // let BluetoothManager settle / process any TCC prompt

    // Resolve MAC -> internal deviceId (try both address spellings).
    std::string devId;
    for (const char* mac : MAC_CANDIDATES) {
        err.clear(); devId.clear();
        int rc = resolve(std::string(mac), &devId, &err);
        printf("Resolve('%s') rc=%d deviceId='%s' err='%s'\n", mac, rc, devId.c_str(), err.c_str());
        runloop(0.2);
        if (!devId.empty()) break;
    }
    if (devId.empty()) {
        printf("Could not resolve a deviceId for the printer. Is Bluetooth allowed for this terminal?\n");
        return 4;
    }

    // Resolve() returns a JSON blob, e.g. {"deviceId":"F013C1789CD0",...}.
    // The Session* calls want just that deviceId value, not the whole blob.
    auto jsonField = [](const std::string& s, const std::string& key) -> std::string {
        std::string pat = "\"" + key + "\":\"";
        auto p = s.find(pat);
        if (p == std::string::npos) return "";
        p += pat.size();
        auto q = s.find('"', p);
        return q == std::string::npos ? "" : s.substr(p, q - p);
    };
    std::string realId = jsonField(devId, "deviceId");
    if (realId.empty()) realId = jsonField(devId, "id");
    if (realId.empty()) { printf("Could not extract deviceId from: %s\n", devId.c_str()); return 4; }
    printf("using deviceId='%s' (name='%s')\n", realId.c_str(), jsonField(devId, "name").c_str());
    devId = realId;

    // Enumerate the device's RFCOMM services (diagnostic): how many channels,
    // which UUIDs/names. Tells us whether channel auto-discovery picks the
    // right one for the print protocol.
    if (svcList) {
        std::string svcs; err.clear();
        int rc = svcList(core, devId, &svcs, &err);
        printf("\nServicesList rc=%d err='%s'\n  %s\n", rc, err.c_str(), svcs.c_str());
        runloop(0.3);
    }

    // Single long open attempt, NO intermediate close (in case a cold connect
    // just needs more time), polling IsOpen every 2s for 30s and re-resolving
    // mid-way to see whether the ACL link ('connected') ever flips true.
    std::optional<std::string> noChannel;            // nullopt => auto-discover via SDP
    err.clear();
    std::string openInfo;
    int orc = sOpen(core, devId, noChannel, &openInfo, &err);
    printf("\nSessionOpen rc=%d err='%s'\n  info=%s\n", orc, err.c_str(), openInfo.c_str());

    bool isOpen = false;
    for (int j = 0; j < 150 && !isOpen; j++) {       // up to ~30s
        runloop(0.2);
        bool now = false; std::string e;
        int rc = sIsOpen ? sIsOpen(core, devId, &now, &e) : -1;
        if (now) isOpen = true;
        if (j % 10 == 0 || now)
            printf("  t=%4.1fs: IsOpen=%d (rc=%d%s%s)\n", j * 0.2, now, rc,
                   e.empty() ? "" : " err=", e.c_str());
        if (j == 40) {                               // ~8s in: is the device connected now?
            std::string info2, e2;
            resolve(std::string("F0:13:C1:78:9C:D0"), &info2, &e2);
            printf("  [re-resolve @8s] %s\n", info2.c_str());
        }
    }
    printf("\n=> IsOpen=%d\n", isOpen);
    if (!isOpen) printf("Session never reached open state.\n");

    // Write the query.
    int written = 0; err.clear();
    int wrc = sWrite(core, devId, (const unsigned char*)FRAME.data(), (int)FRAME.size(), &written, &err);
    printf("Write rc=%d bytesWritten=%d err='%s'\n", wrc, written, err.c_str());
    printf("Sent %zu bytes:\n", FRAME.size());
    hexdump((const unsigned char*)FRAME.data(), FRAME.size());

    // Read for up to ~12s, driving the run loop so inbound-data callbacks fire.
    std::vector<unsigned char> all;
    for (int i = 0; i < 60; i++) {
        runloop(0.2);
        std::vector<unsigned char> chunk;
        err.clear();
        sRead(core, devId, 4096, &chunk, &err);
        if (!chunk.empty()) {
            all.insert(all.end(), chunk.begin(), chunk.end());
            if (i < 50) i = 50;  // small grace window after first data, then wind down
        }
    }

    printf("\n");
    if (!all.empty()) {
        printf("RECEIVED %zu bytes:\n", all.size());
        hexdump(all.data(), all.size());
        printf("\nas text:\n%.*s\n", (int)all.size(), (const char*)all.data());
        printf("\n=> SUCCESS: device replied over bt_core. Framing validated; media enums above.\n");
    } else {
        printf("No reply received over bt_core.\n");
    }

    if (sClose) { err.clear(); sClose(core, devId, &err); }
    dlclose(h);
    return 0;
}
