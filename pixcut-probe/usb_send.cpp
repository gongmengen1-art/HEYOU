// USB path: drive the PixCut S1 through the app's own libht_device_usb_core.dylib
// UsbCore class (IOKit/libusb, synchronous bulk transfers — no async/run-loop/MFi
// pain that blocked the Bluetooth path).
//
// Sends ONE read-only get-prop query on the Command channel (no print/cut) and
// prints the reply.
//
// Build: clang++ -std=c++17 -arch arm64 usb_send.cpp -o usb_send \
//          -Wl,-rpath,"/Applications/Liene Photo.app/Contents/Frameworks"
// Run:   ./usb_send     (printer on USB-C data cable; quit the official app first)

#include <dlfcn.h>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

static const char* LIB =
    "/Applications/Liene Photo.app/Contents/Frameworks/libht_device_usb_core.dylib";

static const unsigned short VID = 0x302c;
static const unsigned short PID = 0x3102;

// UsbChannel enum values = the USB interface numbers (from UsbCore::write disasm:
// channel==2 -> writeCommand, channel==3 -> writeData, else -212).
enum UsbChannel { CH_COMMAND = 2, CH_DATA = 3 };

static const std::string FRAME =
    "cmd json\n"
    "{\"method\":\"get-prop\",\"params\":[\"printer-state\",\"printer-sub-state\","
    "\"printer-state-alerts\",\"media-size\",\"media-type\",\"device-info\","
    "\"firmware-version\"],\"id\":1}";

// Non-virtual member fns via explicit leading `this`.
using Ctor   = void (*)(void* self);
using Open   = int  (*)(void* self, unsigned short vid, unsigned short pid);
using Write  = int  (*)(void* self, int channel, const unsigned char* data, int len, int* written, int timeoutMs);
using Read   = int  (*)(void* self, int channel, unsigned char* buf, int* len, int timeoutMs);
using Close  = void (*)(void* self);

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

    auto ctor  = sym<Ctor>(h,  "_ZN7UsbCoreC1Ev");
    auto open  = sym<Open>(h,  "_ZN7UsbCore4openEtt");
    auto write = sym<Write>(h, "_ZN7UsbCore5writeE10UsbChannelPKhiPii");
    auto read  = sym<Read>(h,  "_ZN7UsbCore4readE10UsbChannelPhPii");
    auto close = sym<Close>(h, "_ZN7UsbCore5closeEv");
    if (!ctor || !open || !write || !read) return 2;

    alignas(16) unsigned char usb[8192] = {0};   // over-allocated UsbCore storage
    ctor(usb);
    printf("UsbCore constructed\n");

    int orc = open(usb, VID, PID);
    printf("UsbCore::open(0x%04x,0x%04x) rc=%d\n", VID, PID, orc);

    int written = 0;
    int wrc = write(usb, CH_COMMAND, (const unsigned char*)FRAME.data(), (int)FRAME.size(), &written, 3000);
    printf("write(Command) rc=%d written=%d / %zu\n", wrc, written, FRAME.size());
    hexdump((const unsigned char*)FRAME.data(), FRAME.size());

    auto drain = [&](int ch, const char* name) -> std::vector<unsigned char> {
        std::vector<unsigned char> all;
        for (int i = 0; i < 5; i++) {
            std::vector<unsigned char> buf(8192, 0);
            int len = (int)buf.size();             // in: capacity
            int rrc = read(usb, ch, buf.data(), &len, 2000);
            printf("  [%s] read rc=%d len=%d\n", name, rrc, len);
            // Only accept a sane, non-empty, sub-capacity result (real replies are small).
            if (rrc >= 0 && len > 0 && len < (int)buf.size()) {
                all.insert(all.end(), buf.begin(), buf.begin() + len);
                break;
            }
            if (rrc < 0) break;                    // hard error: stop
        }
        return all;
    };

    printf("\nReading reply ...\n");
    std::vector<unsigned char> all = drain(CH_COMMAND, "Command");
    if (all.empty()) all = drain(CH_DATA, "Data");  // in case the reply lands on Data

    printf("\n");
    if (!all.empty()) {
        printf("RECEIVED %zu bytes:\n", all.size());
        hexdump(all.data(), all.size());
        printf("\nas text:\n%.*s\n", (int)all.size(), (const char*)all.data());
        printf("\n=> SUCCESS over USB: framing validated; media enums above.\n");
    } else {
        printf("No reply on Command channel. (If open rc!=0, the interface claim may have failed —\n");
        printf(" check whether the official app is still running and holding the USB device.)\n");
    }

    if (close) close(usb);
    dlclose(h);
    return 0;
}
