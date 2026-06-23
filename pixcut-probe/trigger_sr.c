#include <CoreGraphics/CoreGraphics.h>
#include <stdio.h>
int main(){
    // Requires Screen Recording permission; the call triggers the TCC prompt.
    CGImageRef img = CGWindowListCreateImage(CGRectMake(0,0,200,200),
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID, kCGWindowImageDefault);
    if(img){ printf("captured %zux%zu\n", CGImageGetWidth(img), CGImageGetHeight(img)); CFRelease(img); }
    else printf("no image (permission likely needed)\n");
    return 0;
}
