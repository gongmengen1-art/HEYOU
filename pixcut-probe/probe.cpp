// Read-only probe for Liene PixCut S1 (Hannto) ATT protocol framing.
// dlopens libht_device_usb_core.dylib and calls the byte-builder methods
// (RawProtocolManager / ATTProtocolManager) to dump the exact wire frames.
// It NEVER touches DeviceConnector, so nothing is sent to the printer.

#include <dlfcn.h>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <sys/wait.h>
#include <unistd.h>
#include <functional>

static const char* LIB =
    "/Applications/Liene Photo.app/Contents/Frameworks/libht_device_usb_core.dylib";

// Non-virtual member fns share the free-fn ABI with an explicit leading `this`.
// sret (x8 on arm64) is inserted by the compiler from the declared return type.
using CtorRaw     = void (*)(void* self);
using CtorAtt     = void (*)(void* self, void* raw);
using BuildStatus = std::string (*)(void* self);
using BuildJson   = std::string (*)(void* self, const std::string& method, const std::string& params);
using WrapJson    = std::vector<unsigned char> (*)(void* self, const std::string& json);
using WrapData    = std::vector<unsigned char> (*)(void* self, unsigned jobId, const unsigned char* data, int len);
using HeaderSize  = int (*)(void* self, unsigned jobId, int type);
using MaxPkt      = int (*)(void* self);
using EncodeJobId = void (*)(void* self, unsigned jobId, unsigned char* out);

static void* sym(void* h, const char* name) {
    void* p = dlsym(h, name);
    if (!p) { fprintf(stderr, "MISSING SYMBOL: %s\n", name); }
    return p;
}

static void hexdump(const char* label, const unsigned char* p, size_t n) {
    printf("%s (%zu bytes):\n", label, n);
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
    printf("dlopen OK: %s\n\n", LIB);

    auto ctorRaw   = (CtorRaw)     sym(h, "_ZN18RawProtocolManagerC1Ev");
    auto ctorAtt   = (CtorAtt)     sym(h, "_ZN18ATTProtocolManagerC1EP18RawProtocolManager");
    auto bStatus   = (BuildStatus) sym(h, "_ZN18RawProtocolManager27buildGetDeviceStatusCommandEv");
    auto bJson     = (BuildJson)   sym(h, "_ZN18RawProtocolManager16buildJsonCommandERKNSt3__112basic_stringIcNS0_11char_traitsIcEENS0_9allocatorIcEEEES8_");
    auto wrapJson  = (WrapJson)    sym(h, "_ZN18ATTProtocolManager15wrapJsonCommandERKNSt3__112basic_stringIcNS0_11char_traitsIcEENS0_9allocatorIcEEEE");
    auto wrapData  = (WrapData)    sym(h, "_ZN18ATTProtocolManager14wrapDataPacketEjPKhi");
    auto hdrSize   = (HeaderSize)  sym(h, "_ZNK18ATTProtocolManager21getProtocolHeaderSizeEji");
    auto maxPkt    = (MaxPkt)      sym(h, "_ZNK18ATTProtocolManager16getMaxPacketSizeEv");
    auto encJobId  = (EncodeJobId) sym(h, "_ZN18ATTProtocolManager13encodeJobIdLEEjPh");

    if (!ctorRaw || !ctorAtt || !wrapJson) { fprintf(stderr, "core symbols missing, abort\n"); return 2; }

    // Over-allocate, zeroed storage for the two objects (real sizeof unknown).
    alignas(16) unsigned char rawObj[1024] = {0};
    alignas(16) unsigned char attObj[1024] = {0};
    ctorRaw(rawObj);
    ctorAtt(attObj, rawObj);
    printf("constructed RawProtocolManager + ATTProtocolManager\n\n");

    if (maxPkt)  printf("getMaxPacketSize()            = %d\n", maxPkt(attObj));
    if (hdrSize) {
        for (int t = 0; t <= 4; t++)
            printf("getProtocolHeaderSize(job=1,t=%d) = %d\n", t, hdrSize(attObj, 1, t));
    }
    printf("\n");

    if (encJobId) {
        unsigned char jb[8] = {0};
        encJobId(attObj, 0x01020304u, jb);
        hexdump("encodeJobIdLE(0x01020304)", jb, 4);
        printf("\n");
    }

    if (bStatus) {
        std::string js = bStatus(rawObj);  // build* is a RawProtocolManager method
        printf("buildGetDeviceStatusCommand() JSON:\n  %s\n\n", js.c_str());

        auto frame = wrapJson(attObj, js);
        hexdump("wrapJsonCommand(get-device-status)", frame.data(), frame.size());
        printf("\n");
    }

    if (bJson) {
        std::string js = bJson(rawObj, "print-job",
                               "{\"copies\":1,\"media-size\":\"60x60\",\"document-format\":\"image/pwg-raster\"}");
        printf("buildJsonCommand(print-job, ...) JSON:\n  %s\n\n", js.c_str());
        auto frame = wrapJson(attObj, js);
        hexdump("wrapJsonCommand(print-job)", frame.data(), frame.size());
        printf("\n");
    }

    // --- Reveal print/cut job JSON schemas by feeding ZEROED param structs.
    // A zeroed libc++ std::string/vector is a valid empty value, so the builder
    // emits the full key set with empty/zero values. Each call is fork()-isolated
    // in case a zeroed field gets dereferenced and crashes.
    using BuildFromParams = std::string (*)(void* self, const void* params);
    auto runIsolated = [](const char* label, std::function<void()> fn) {
        fflush(stdout);
        pid_t pid = fork();
        if (pid == 0) { fn(); fflush(stdout); _exit(0); }
        int st = 0; waitpid(pid, &st, 0);
        if (!WIFEXITED(st) || WEXITSTATUS(st) != 0)
            printf("  [%s crashed/exited abnormally: status=%d]\n", label, st);
    };
    struct { const char* name; const char* sym; } builders[] = {
        {"buildCreateJobCommand",         "_ZN18RawProtocolManager21buildCreateJobCommandERK9JobParams"},
        {"serializeJobParams",            "_ZN18RawProtocolManager18serializeJobParamsERK9JobParams"},
        {"buildCreatePrintJobCommand",    "_ZN18RawProtocolManager26buildCreatePrintJobCommandERK14PrintJobParams"},
        {"buildCreatePrintCutJobCommand", "_ZN18RawProtocolManager29buildCreatePrintCutJobCommandERK17PrintCutJobParams"},
        {"buildCreateCutJobCommand",      "_ZN18RawProtocolManager24buildCreateCutJobCommandERK12CutJobParams"},
    };
    // No-arg read-only query builders -> exact JSON to bake into status_query.py
    using BuildNoArg = std::string (*)(void* self);
    struct { const char* name; const char* sym; } queries[] = {
        {"get-device-status",   "_ZN18RawProtocolManager27buildGetDeviceStatusCommandEv"},
        {"get-media-size",      "_ZN18RawProtocolManager24buildGetMediaSizeCommandEv"},
        {"get-media-type",      "_ZN18RawProtocolManager24buildGetMediaTypeCommandEv"},
        {"get-device-info",     "_ZN18RawProtocolManager25buildGetDeviceInfoCommandEv"},
        {"get-firmware-version","_ZN18RawProtocolManager30buildGetFirmwareVersionCommandEv"},
        {"get-auto-off",        "_ZN18RawProtocolManager30buildGetAutoOffIntervalCommandEv"},
    };
    printf("=== read-only query command JSONs ===\n");
    for (auto& q : queries) {
        auto fn = (BuildNoArg)dlsym(h, q.sym);
        if (!fn) { printf("  %s: SYMBOL MISSING\n", q.name); continue; }
        std::string js = fn(rawObj);
        printf("%-20s %s\n", q.name, js.c_str());
    }
    printf("\n");

    printf("=== JSON schemas from builders (zeroed params) ===\n");
    for (auto& b : builders) {
        auto fn = (BuildFromParams)dlsym(h, b.sym);
        if (!fn) { printf("  %s: SYMBOL MISSING\n", b.name); continue; }
        runIsolated(b.name, [&]() {
            alignas(16) unsigned char params[2048] = {0};
            std::string js = fn(rawObj, params);
            printf("%s:\n  %s\n", b.name, js.c_str());
        });
    }
    printf("\n");

    if (wrapData) {
        unsigned char payload[40];
        for (int i = 0; i < 40; i++) payload[i] = (unsigned char)i;
        auto frame = wrapData(attObj, 0x11223344u, payload, sizeof(payload));
        hexdump("wrapDataPacket(job=0x11223344, 40 bytes 0x00..0x27)", frame.data(), frame.size());
        printf("\n");
    }

    dlclose(h);
    return 0;
}
