// axenable <pid> : force-enable accessibility on a Flutter/Chromium app and dump its AX tree.
// Sets kAXManualAccessibility + AXEnhancedUserInterface on the app element (the trigger Flutter
// uses to build its semantics tree), then walks windows -> descendants printing role/title/pos/size.
#include <ApplicationServices/ApplicationServices.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static char* cf2c(CFStringRef s){
  if(!s) return NULL;
  CFIndex n = CFStringGetMaximumSizeForEncoding(CFStringGetLength(s), kCFStringEncodingUTF8)+1;
  char* b = malloc(n); b[0]=0;
  CFStringGetCString(s, b, n, kCFStringEncodingUTF8);
  return b;
}
static CFStringRef getStr(AXUIElementRef e, CFStringRef attr){
  CFTypeRef v=NULL;
  if(AXUIElementCopyAttributeValue(e, attr, &v)==kAXErrorSuccess && v){
    if(CFGetTypeID(v)==CFStringGetTypeID()) return (CFStringRef)v;
    CFRelease(v);
  }
  return NULL;
}
static int count=0;
static void walk(AXUIElementRef e, int depth){
  if(depth>40 || count>4000) return;
  count++;
  CFStringRef role = getStr(e, kAXRoleAttribute);
  CFStringRef title= getStr(e, kAXTitleAttribute);
  CFStringRef val  = getStr(e, kAXValueAttribute);
  CFStringRef desc  = getStr(e, kAXDescriptionAttribute);
  char *r=cf2c(role),*t=cf2c(title),*v=cf2c(val),*d=cf2c(desc);
  const char* label = (t&&t[0])?t : (v&&v[0])?v : (d&&d[0])?d : "";
  // position/size
  CGPoint pos={0,0}; CGSize sz={0,0};
  CFTypeRef pv=NULL,sv=NULL;
  if(AXUIElementCopyAttributeValue(e,kAXPositionAttribute,&pv)==kAXErrorSuccess&&pv){AXValueGetValue(pv,kAXValueCGPointType,&pos);CFRelease(pv);}
  if(AXUIElementCopyAttributeValue(e,kAXSizeAttribute,&sv)==kAXErrorSuccess&&sv){AXValueGetValue(sv,kAXValueCGSizeType,&sz);CFRelease(sv);}
  if(r && (label[0] || (sz.width>0))){
    printf("%*s%s '%s' @%.0f,%.0f [%.0fx%.0f]\n", depth*2, "", r?r:"?", label, pos.x,pos.y,sz.width,sz.height);
  }
  free(r);free(t);free(v);free(d);
  if(role)CFRelease(role); if(title)CFRelease(title); if(val)CFRelease(val); if(desc)CFRelease(desc);
  CFArrayRef kids=NULL;
  if(AXUIElementCopyAttributeValue(e,kAXChildrenAttribute,(CFTypeRef*)&kids)==kAXErrorSuccess && kids){
    CFIndex n=CFArrayGetCount(kids);
    for(CFIndex i=0;i<n;i++) walk((AXUIElementRef)CFArrayGetValueAtIndex(kids,i), depth+1);
    CFRelease(kids);
  }
}
int main(int argc,char**argv){
  if(argc<2){fprintf(stderr,"usage: axenable <pid>\n");return 1;}
  pid_t pid=atoi(argv[1]);
  AXUIElementRef app=AXUIElementCreateApplication(pid);
  // The two flags that wake Chromium/Flutter accessibility:
  AXUIElementSetAttributeValue(app, CFSTR("AXManualAccessibility"), kCFBooleanTrue);
  AXUIElementSetAttributeValue(app, CFSTR("AXEnhancedUserInterface"), kCFBooleanTrue);
  // give the engine a moment to build the semantics tree
  for(int i=0;i<10;i++){
    CFArrayRef wins=NULL;
    AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, (CFTypeRef*)&wins);
    int total=0;
    if(wins){ for(CFIndex w=0;w<CFArrayGetCount(wins);w++){ CFArrayRef kids=NULL; AXUIElementCopyAttributeValue((AXUIElementRef)CFArrayGetValueAtIndex(wins,w),kAXChildrenAttribute,(CFTypeRef*)&kids); if(kids){total+=CFArrayGetCount(kids);CFRelease(kids);} } CFRelease(wins); }
    if(total>0) break;
    usleep(300000);
  }
  CFArrayRef wins=NULL;
  AXUIElementCopyAttributeValue(app, kAXWindowsAttribute, (CFTypeRef*)&wins);
  printf("pid=%d windows=%ld\n", pid, wins?CFArrayGetCount(wins):0);
  if(wins){ for(CFIndex w=0;w<CFArrayGetCount(wins);w++) walk((AXUIElementRef)CFArrayGetValueAtIndex(wins,w),0); CFRelease(wins); }
  printf("(total nodes visited: %d)\n", count);
  return 0;
}
