import ScreenCaptureKit
import Foundation
let sem = DispatchSemaphore(value: 0)
if #available(macOS 12.3, *) {
  SCShareableContent.getWithCompletionHandler { content, err in
    if let c = content { print("ScreenCaptureKit OK — displays:\(c.displays.count) windows:\(c.windows.count)") }
    else { print("需要授权 / err: \(String(describing: err))") }
    sem.signal()
  }
  sem.wait()
} else { print("macOS too old") }
