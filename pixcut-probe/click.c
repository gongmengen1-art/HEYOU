// Tiny coordinate clicker using CGEvent (needs Accessibility permission, which Terminal has).
// Usage: ./click <x> <y>   — moves the mouse to (x,y) and left-clicks.
#include <ApplicationServices/ApplicationServices.h>
#include <unistd.h>
#include <stdlib.h>
int main(int argc, char** argv) {
    if (argc < 3) { return 1; }
    CGPoint p = CGPointMake(atof(argv[1]), atof(argv[2]));
    CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(NULL, kCGEventMouseMoved, p, kCGMouseButtonLeft));
    usleep(120000);
    CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(NULL, kCGEventLeftMouseDown, p, kCGMouseButtonLeft));
    usleep(60000);
    CGEventPost(kCGHIDEventTap, CGEventCreateMouseEvent(NULL, kCGEventLeftMouseUp, p, kCGMouseButtonLeft));
    return 0;
}
