#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""pixcut_win.py — Windows port of the macOS Liene-app UI-automation (PixCut S1 printing).

The macOS driver (print_via_app.py) drives the Liene Photo app via osascript / CGEvent /
screencapture. This module does the same on Windows with:
  * pyautogui  — click / move / hotkey / screenshot
  * pygetwindow — locate + activate the Liene window, read its rect
  * pyperclip  — clipboard (all text entry is clipboard-paste, so the Chinese IME
                 can never intercept/mangle keystrokes)
  * psutil     — find / restart the Liene process

DRIVER ARCHITECTURE (settled 2026-07-06 after canvasprobe + fluttertest):
  * The app is a MIX: the Home/community content is a WebView2 page ('mingshashan' at
    jiyin.hannto.com), but the 创建设计 modal AND the whole editor are NATIVE FLUTTER UI
    (open editor => still only the home CDP target; modal absent from the DOM).
  * Input rules learned the hard way:
      - WEB content ignores ALL OS-injected input (SendInput 'succeeds', zero effect —
        dropped in the Flutter->webview forwarding), but CDP Input events work fine.
      - FLUTTER UI accepts SendInput (fluttertest clicked 用于4*7相纸 and the editor
        opened) — the mac-style pixel automation works for everything native.
  * So the driver is HYBRID: CDP click for the home 画板 button, SendInput pixel clicks
    (offsets measured off OS screenshots, window-relative) for the Flutter modal and the
    editor. Every step saves an OS screenshot to logs\cal_NN_<step>.png.
  * The Windows Flutter editor is NOT the mac web editor: layout/labels differ (left
    toolbar 模板库/元素/AI实验室/上传/文字/形状/我的项目; right panel 背景/图片填充;
    top-right teal 制作). Its post-upload UI is being calibrated round by round.

COMMANDS
  probe          report geometry + full screenshot (calibration step 1)
  clicktest      diagnose click injection: tries pyautogui / SendInput / PostMessage on the
                 home nav tabs and reports which one actually changes the page
                 (2026-07-06 result: ALL THREE silently dropped — UIPI/hook-style filtering;
                 hence the CDP path below)
  cdp            restart the Liene app with WebView2 remote debugging enabled
                 (--remote-debugging-port=9222) and probe the Creativerse page over the
                 Chrome DevTools Protocol — DOM-level control, no OS input injection at all
  dryrun <img>   full flow UP TO the 切割预览 — never clicks 切割, uses NO ribbon.
                 Saves logs\cal_NN_<step>.png after every step. Send those back.
  logscan        search the disk for the Liene app's own log files (job polling)
  print <img>    real print — DISABLED until the dryrun is verified (CALIBRATED=False)

While dryrun runs: DO NOT touch mouse/keyboard. Abort = slam the mouse into the
top-left screen corner (pyautogui failsafe).
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time

APP_TITLE_HINTS = ("Liene", "极印", "Creativerse", "小蓝盒", "Photo")
PROC_HINTS = ("liene", "creativerse", "hannto")
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

# Canvas paper size (inches) — the blank "用于4*7相纸" canvas.
CANVAS_W_IN, CANVAS_H_IN = 4.0, 7.0

# Flip to True only after a Windows dryrun has been verified end-to-end.
# The `print` command refuses to run while False (ribbon safety).
CALIBRATED = False

# Expected window size (from probe 2026-07-06). Offsets are only valid near this.
EXPECT_W, EXPECT_H = 1296, 768

# (The per-control pixel OFFSETS and teal-detection rects that drove the first dryrun
# attempt were removed with the pixel-click path — the CDP driver finds controls by their
# DOM text instead.)


def log(*a):
    print("[pixcut_win]", *a, flush=True)


def _require_win():
    if not sys.platform.startswith("win"):
        sys.exit("pixcut_win.py runs on Windows only (use print_via_app.py on macOS).")


def _dpi_aware():
    """Make the process DPI-aware so clicks, window rects and screenshots are all in the SAME
    physical-pixel space at any display scaling (otherwise Windows virtualizes coordinates)."""
    import ctypes
    for fn in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),      # per-monitor v2
               lambda: ctypes.windll.user32.SetProcessDPIAware()):          # fallback
        try:
            fn(); return
        except Exception:  # noqa: BLE001
            continue


def _deps():
    """Import the Windows automation libs lazily with a clear message if they're missing."""
    try:
        import pyautogui
        import pygetwindow as gw
        import pyperclip
        from PIL import Image
    except ImportError as e:
        sys.exit(f"Windows automation deps missing ({e}). Run: uv sync  "
                 "(installs pyautogui/pygetwindow/pyperclip on Windows).")
    pyautogui.FAILSAFE = True   # mouse to top-left corner = emergency abort
    return pyautogui, gw, pyperclip, Image


def find_liene_window(gw):
    """Return the Liene app window (pygetwindow Win) by matching title hints, or None."""
    for title in gw.getAllTitles():
        t = title.strip()
        if t and any(h.lower() in t.lower() for h in APP_TITLE_HINTS):
            wins = gw.getWindowsWithTitle(title)
            if wins:
                return wins[0]
    return None


def _screen_scale():
    """System DPI scale factor (1.0 == 100%). Reported for reference; the driver works in
    physical pixels regardless, but OFFSETS are only valid at the scale they were calibrated."""
    try:
        import ctypes
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    except Exception:  # noqa: BLE001
        return 1.0


# ---- calibration probe -----------------------------------------------------
def probe():
    _require_win()
    _dpi_aware()
    pyautogui, gw, pyperclip, Image = _deps()
    os.makedirs(LOGS_DIR, exist_ok=True)
    shot_path = os.path.join(LOGS_DIR, "pixcut_probe.png")

    sw, sh = pyautogui.size()
    scale = _screen_scale()
    print(f"[probe] screen size (physical px): {sw}x{sh}")
    print(f"[probe] display scale: {scale:.2f}  ({int(scale * 100)}%)  "
          f"[keep this fixed; offsets are calibrated at this scale]")

    titles = sorted({t for t in gw.getAllTitles() if t.strip()})
    print(f"[probe] {len(titles)} visible windows:")
    for t in titles:
        print(f"    | {t}")

    win = find_liene_window(gw)
    if win is not None:
        print(f"[probe] LIENE window: title={win.title!r}  "
              f"origin=({win.left},{win.top})  size={win.width}x{win.height}")
        try:
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(0.8)
        except Exception as e:  # noqa: BLE001
            print(f"[probe] (could not activate window: {e})")
    else:
        print(f"[probe] Liene window NOT found by title hints {APP_TITLE_HINTS}")
        print("[probe] -> tell me which of the titles above is the Liene app window")

    try:
        import psutil
        cands = []
        for p in psutil.process_iter(["name", "exe"]):
            name = (p.info.get("name") or "")
            exe = (p.info.get("exe") or "")
            if any(h in name.lower() or h in exe.lower() for h in PROC_HINTS):
                cands.append((p.pid, name, exe))
        print(f"[probe] candidate Liene processes: {cands[:10] or 'NONE (name hint miss)'}")
    except Exception as e:  # noqa: BLE001
        print(f"[probe] process scan failed: {e}")

    img = pyautogui.screenshot()
    img.save(shot_path)
    print(f"[probe] screenshot {img.width}x{img.height} saved: {shot_path}")
    print("[probe] DONE — send me logs\\pixcut_probe.png plus everything printed above.")


# ---- low-level click injection ------------------------------------------------
# The 2026-07-06 dryrun showed pyautogui clicks (SetCursorPos + mouse_event) never reach the
# Liene app at all (6+ clicks, zero UI change, screenshots fine). SendInput with ABSOLUTE
# coordinates embeds the position in the same injected event as the button press, so a cursor
# snap-back (remote-control software, etc.) can't race it. PostMessage bypasses the cursor
# entirely by posting WM_LBUTTONDOWN/UP straight to the window under the point.

def _send_click(x, y):
    """Click via SendInput: one atomic batch of (move+down, move+up) at ABSOLUTE coords.
    Returns the number of events injected (2 == success)."""
    import ctypes
    user32 = ctypes.windll.user32
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("mi", MOUSEINPUT)]

    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    ax = int(round(x * 65535 / (sw - 1)))
    ay = int(round(y * 65535 / (sh - 1)))
    MOVE, ABS, LDOWN, LUP = 0x0001, 0x8000, 0x0002, 0x0004
    events = (INPUT * 2)(
        INPUT(0, MOUSEINPUT(ax, ay, 0, MOVE | ABS | LDOWN, 0, 0)),
        INPUT(0, MOUSEINPUT(ax, ay, 0, MOVE | ABS | LUP, 0, 0)),
    )
    return user32.SendInput(2, events, ctypes.sizeof(INPUT))


def _send_dblclick(x, y):
    """SendInput double-click at absolute coords (two down/up pairs). Used to put a Flutter
    numeric field into text-edit mode + select its value (a single programmatic click only
    places the caret and leaves the field uneditable)."""
    _send_click(x, y)
    time.sleep(0.08)
    _send_click(x, y)


def _post_click(x, y):
    """Click via PostMessage to the deepest window under the screen point (no cursor at all).
    Returns (hwnd, class_name) of the target window."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pt = wintypes.POINT(int(x), int(y))
    hwnd = user32.WindowFromPoint(pt)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    client = wintypes.POINT(int(x), int(y))
    user32.ScreenToClient(hwnd, ctypes.byref(client))
    lparam = ((client.y & 0xFFFF) << 16) | (client.x & 0xFFFF)
    WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON = 0x0201, 0x0202, 0x0001
    user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
    time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lparam)
    return hwnd, cls.value


def _point_diag(x, y):
    """Report which window actually sits under a screen point (overlay detector)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    pt = wintypes.POINT(int(x), int(y))
    hwnd = user32.WindowFromPoint(pt)
    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = "?"
    try:
        import psutil
        exe = psutil.Process(pid.value).name()
    except Exception:  # noqa: BLE001
        pass
    root = user32.GetAncestor(hwnd, 2)  # GA_ROOT
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(root, title, 256)
    log(f"  under ({int(x)},{int(y)}): class={cls.value!r} pid={pid.value} exe={exe} "
        f"root_title={title.value!r}")
    return exe


def _foreground_title():
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


# ---- input / vision primitives ----------------------------------------------
class UI:
    """Windows automation primitives, mirroring print_via_app.py's UI class. Coordinates are
    physical pixels; (ox, oy) is the Liene window's top-left. scale stays 1.0 on Windows
    (we are DPI-aware, so screenshot px == click px) but is kept so the vision helpers stay
    symmetric with macOS (which has Retina scale 2)."""

    def __init__(self, ox: int, oy: int, scale: float = 1.0):
        self.ox, self.oy, self.scale = ox, oy, scale
        self._pg, self._gw, self._clip, self._Image = _deps()

    def activate(self):
        win = find_liene_window(self._gw)
        if win is not None:
            try:
                if win.isMinimized:
                    win.restore()
                win.activate()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.4)

    def shot(self, path=None):
        self.activate()
        time.sleep(0.2)
        img = self._pg.screenshot()
        if path:
            img.save(path)
        return img.convert("RGB")

    # px (screenshot) <-> logical points; identical on Windows (scale 1)
    def px2pt(self, px, py):
        return px / self.scale, py / self.scale

    def pt2px(self, x, y):
        return int(x * self.scale), int(y * self.scale)


# ---- step snapshots (calibration) -------------------------------------------
SNAPS: list[tuple[str, str]] = []


def clear_snaps():
    os.makedirs(LOGS_DIR, exist_ok=True)
    for f in glob.glob(os.path.join(LOGS_DIR, "cal_*.png")):
        try:
            os.remove(f)
        except OSError:
            pass
    SNAPS.clear()


# ---- window setup -----------------------------------------------------------
def make_ui():
    _require_win()
    _dpi_aware()
    pyautogui, gw, pyperclip, Image = _deps()
    win = find_liene_window(gw)
    if win is None:
        sys.exit("ERROR: Liene window not found. Open + sign in to 极印 Photo first.")
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(0.8)
    except Exception:  # noqa: BLE001
        pass
    log(f"window {win.title!r} @({win.left},{win.top}) {win.width}x{win.height} "
        f"scale={_screen_scale():.2f}")
    if abs(win.width - EXPECT_W) > 80 or abs(win.height - EXPECT_H) > 60:
        log(f"WARN: window size {win.width}x{win.height} differs from calibrated "
            f"{EXPECT_W}x{EXPECT_H}; offsets may be off. Don't resize the app window.")
    return UI(win.left, win.top, 1.0)


# ---- click-injection diagnosis ------------------------------------------------
def _content_diff(a, b, ui):
    """Fraction of sampled pixels that changed in the web-content region (rel 170,130-1130,700).
    Used to tell whether a click actually navigated the page."""
    ax0, ay0 = ui.pt2px(ui.ox + 170, ui.oy + 130)
    ax1, ay1 = ui.pt2px(ui.ox + 1130, ui.oy + 700)
    pa, pb = a.load(), b.load()
    total = changed = 0
    for y in range(int(ay0), min(a.height, b.height, int(ay1)), 4):
        for x in range(int(ax0), min(a.width, b.width, int(ax1)), 4):
            total += 1
            ra, ga, ba = pa[x, y]
            rb, gb, bb = pb[x, y]
            if abs(ra - rb) + abs(ga - gb) + abs(ba - bb) > 60:
                changed += 1
    return changed / total if total else 0.0


def clicktest():
    """Diagnose why clicks don't reach the app: try 3 injection methods on the home nav tabs
    (模板/元素/探索 — clicking one visibly changes the page) and report which method works.
    Run this ON THE HOME PAGE. Harmless: only nav tabs are clicked."""
    ui = make_ui()
    clear_snaps()

    log(f"foreground before activate: {_foreground_title()!r}")
    ui.activate()
    log(f"foreground after  activate: {_foreground_title()!r}")

    try:
        import ctypes
        log(f"python elevated (admin): {bool(ctypes.windll.shell32.IsUserAnAdmin())}")
    except Exception:  # noqa: BLE001
        pass

    # cursor snap-back check: move the mouse and see where it actually ends up
    tx, ty = ui.ox + 363, ui.oy + 55           # 模板 tab
    ui._pg.moveTo(tx, ty)
    time.sleep(0.3)
    px, py = ui._pg.position()
    log(f"moveTo({tx},{ty}) -> cursor now at ({px},{py})"
        + ("  [OK]" if abs(px - tx) <= 2 and abs(py - ty) <= 2 else "  [SNAPPED BACK!]"))

    # what actually sits under our click targets? (transparent overlay detector)
    log("window under the click targets:")
    _point_diag(ui.ox + 1101, ui.oy + 55)      # + 画板 button
    _point_diag(tx, ty)                        # 模板 tab

    targets = [("moban", 363, 55), ("yuansu", 411, 55), ("tansuo", 316, 55)]
    methods = [
        ("pyautogui", lambda x, y: ui._pg.click(int(x), int(y))),
        ("sendinput", lambda x, y: log(f"    SendInput injected "
                                       f"{_send_click(int(x), int(y))}/2 events")),
        ("postmessage", lambda x, y: log(f"    PostMessage -> hwnd class "
                                         f"{_post_click(int(x), int(y))[1]!r}")),
    ]
    results = {}
    for (mname, fn), (tname, dx, dy) in zip(methods, targets):
        ui.activate()
        before = ui.shot()
        log(f"[{mname}] clicking {tname} tab at rel ({dx},{dy})...")
        fn(ui.ox + dx, ui.oy + dy)
        time.sleep(2.5)
        after = ui.shot(os.path.join(LOGS_DIR, f"cal_click_{mname}.png"))
        frac = _content_diff(before, after, ui)
        results[mname] = frac
        log(f"[{mname}] content change: {frac:.1%} -> "
            + ("PAGE CHANGED (works!)" if frac > 0.02 else "no change (blocked)"))

    log("=" * 60)
    for m, frac in results.items():
        log(f"  {m:12s} {'WORKS' if frac > 0.02 else 'blocked':8s} ({frac:.1%})")
    log("-> send me this console output + logs\\cal_click_*.png")


# ---- CDP (Chrome DevTools Protocol) over the app's WebView2 --------------------
# clicktest showed ALL synthetic OS input (pyautogui / SendInput / PostMessage) is silently
# dropped before reaching the app. The Creativerse UI is a WebView2 (Edge) though, and
# WebView2 honours WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS, so relaunching the app with
# --remote-debugging-port gives us full DOM-level control (click by selector, set fields,
# feed the file input directly) with no OS input injection anywhere.

CDP_PORT = 9222
LIENE_EXE_FALLBACK = r"C:\Program Files\Liene Photo\liene_photo_pc.exe"


def liene_procs():
    import psutil
    out = []
    for p in psutil.process_iter(["name", "exe", "username"]):
        if (p.info.get("name") or "").lower() == "liene_photo_pc.exe":
            out.append(p)
    return out


APP_LOG = os.path.join(LOGS_DIR, "liene_app.log")


def restart_liene_with_cdp():
    """Kill the Liene app and relaunch it with WebView2 remote debugging enabled.
    The WebView2 user-data dir is untouched, so the Creativerse sign-in persists.
    The app streams its own log ([REQ]/[RESP] device traffic incl. job states) to stdout,
    so capture it to logs\\liene_app.log — that's our job-completion signal on Windows
    (there is no on-disk app log like on macOS) and it keeps the console from flooding."""
    import subprocess
    import psutil
    exe = LIENE_EXE_FALLBACK
    procs = liene_procs()
    for p in procs:
        try:
            exe = p.info.get("exe") or exe
            log(f"killing liene_photo_pc.exe pid={p.pid} (user={p.info.get('username')})")
            p.terminate()
        except Exception as e:  # noqa: BLE001
            log(f"  terminate failed: {e}")
    if procs:
        psutil.wait_procs(procs, timeout=10)
        time.sleep(1.0)
    if not os.path.exists(exe):
        sys.exit(f"ERROR: Liene exe not found at {exe}")
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
        f"--remote-debugging-port={CDP_PORT} --remote-allow-origins=*")
    DETACHED = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    os.makedirs(LOGS_DIR, exist_ok=True)
    logfh = open(APP_LOG, "ab")   # the app keeps the inherited handle after we exit
    subprocess.Popen([exe], cwd=os.path.dirname(exe), env=env, creationflags=DETACHED,
                     stdout=logfh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    logfh.close()
    log(f"relaunched {exe} with --remote-debugging-port={CDP_PORT}")
    log(f"app log captured to {APP_LOG}")


def cdp_pages(timeout=60.0):
    """Poll the CDP HTTP endpoint until a REAL page target appears (the webview starts as
    about:blank before navigating to Creativerse). Returns all page targets — possibly only
    blank ones if the wait times out."""
    import json
    import urllib.request
    pages = []
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=2) as r:
                targets = json.loads(r.read().decode("utf-8"))
            pages = [t for t in targets if t.get("type") == "page"]
            if any((p.get("url") or "").startswith(("http", "file")) for p in pages):
                return pages
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
    return pages


class CdpSession:
    """Minimal CDP client over one page's webSocketDebuggerUrl."""

    def __init__(self, ws_url):
        try:
            import websocket
        except ImportError:
            sys.exit("websocket-client missing — run: uv sync")
        # suppress_origin: Chromium 111+ rejects websocket clients that send an Origin
        # header unless --remote-allow-origins matches; sending none is always accepted.
        self._ws = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)
        self._id = 0
        self.events = []          # buffered CDP events (e.g. Page.fileChooserOpened)

    def cmd(self, method, **params):
        import json
        self._id += 1
        self._ws.send(json.dumps({"id": self._id, "method": method, "params": params}))
        while True:
            msg = json.loads(self._ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method}: {msg['error']}")
                return msg.get("result", {})
            if msg.get("method"):
                self.events.append(msg)
                if len(self.events) > 300:
                    del self.events[:150]

    def wait_event(self, method, timeout=8.0):
        """Return the next event with this method (buffered or incoming), or None."""
        import json
        for i, ev in enumerate(self.events):
            if ev.get("method") == method:
                return self.events.pop(i)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self._ws.settimeout(max(0.3, deadline - time.time()))
                msg = json.loads(self._ws.recv())
            except Exception:  # noqa: BLE001  (timeout)
                break
            finally:
                try:
                    self._ws.settimeout(15)
                except Exception:  # noqa: BLE001
                    pass
            if msg.get("method") == method:
                return msg
            if msg.get("method"):
                self.events.append(msg)
        return None

    def eval(self, expr, await_promise=False):
        r = self.cmd("Runtime.evaluate", expression=expr, returnByValue=True,
                     awaitPromise=await_promise)
        res = r.get("result", {})
        if res.get("subtype") == "error":
            raise RuntimeError(f"JS error: {res.get('description')}")
        return res.get("value")

    def close(self):
        try:
            self._ws.close()
        except Exception:  # noqa: BLE001
            pass


def cdp():
    """Restart the app with remote debugging and dump DOM ground truth from the
    Creativerse page: title/url, visible button texts, file inputs. READ-ONLY."""
    _require_win()
    restart_liene_with_cdp()
    log("waiting for the app + CDP endpoint (up to ~45s)...")
    pages = cdp_pages()
    if not pages:
        log("ERROR: no CDP page targets appeared. Possible causes: the app pins its own")
        log("  additionalBrowserArguments (env var ignored) or the port is blocked.")
        log("  -> send me this output; fallback is the registry policy or another port.")
        return
    log(f"{len(pages)} CDP page target(s):")
    for t in pages:
        log(f"  title={t.get('title')!r}  url={t.get('url')!r}")
    # pick the Creativerse page (title 'mingshashan' seen on both mac + win); fall back to
    # any real-URL page before settling for a still-blank one
    pick = next((t for t in pages if "mingshashan" in (t.get("title") or "").lower()),
                next((t for t in pages
                      if (t.get("url") or "").startswith(("http", "file"))), pages[0]))
    log(f"probing page {pick.get('title')!r} ...")
    s = CdpSession(pick["webSocketDebuggerUrl"])
    try:
        log(f"  document.title = {s.eval('document.title')!r}")
        log(f"  location.href  = {s.eval('location.href')!r}")
        texts = s.eval(
            "[...document.querySelectorAll('button,[role=button],a,[class*=btn],"
            "[class*=tab]')].map(e=>e.innerText&&e.innerText.trim()).filter(t=>t&&"
            "t.length<20).slice(0,60)")
        log(f"  clickable texts: {texts}")
        nfile = s.eval("document.querySelectorAll('input[type=file]').length")
        log(f"  file inputs on page: {nfile}")
        body = s.eval("document.body.innerText.replace(/\\s+/g,' ').slice(0,600)")
        log(f"  body text head: {body!r}")
    finally:
        s.close()
    log("CDP PROBE OK — DOM access works; the driver can move to CDP entirely.")
    log("-> send me this console output.")


# ---- CDP UI driver --------------------------------------------------------------
def _js_str(s):
    import json as _json
    return _json.dumps(str(s), ensure_ascii=False)


class CdpUI:
    """DOM-level driver for the Creativerse webview. All interaction goes through CDP:
    clicks are trusted in-page Input events at an element's rect (found by its TEXT, so
    nothing depends on window pixels), uploads feed the file chooser directly, and the
    高级 W/H/X/Y fields are read/written as DOM inputs."""

    def __init__(self):
        pages = cdp_pages(timeout=6.0)
        if not any((p.get("url") or "").startswith("http") for p in pages):
            log("CDP endpoint not up — restarting the app with remote debugging")
            restart_liene_with_cdp()
            pages = cdp_pages(timeout=60.0)
        real = [p for p in pages if (p.get("url") or "").startswith("http")]
        if not real:
            sys.exit("ERROR: no CDP page target appeared — run the 'cdp' command and "
                     "send me its output.")
        self.known = {p.get("id") for p in pages}
        self.s = None
        self._attach(next((p for p in real
                           if "mingshashan" in (p.get("title") or "").lower()), real[0]))

    def _attach(self, target):
        if self.s:
            self.s.close()
        self.s = CdpSession(target["webSocketDebuggerUrl"])
        self.target = target
        for dom in ("Page.enable", "DOM.enable", "Runtime.enable"):
            try:
                self.s.cmd(dom)
            except Exception as e:  # noqa: BLE001
                log(f"  ({dom} failed: {e})")
        log(f"attached: {target.get('title')!r} {target.get('url')!r}")

    def repick_new(self, timeout=10.0):
        """The app may open a NEW webview for the editor (one per 画板 tab); if a new page
        target appears, attach to it. Returns True if switched."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            for p in cdp_pages(timeout=1.0):
                pid = p.get("id")
                if pid and pid not in self.known and (p.get("url") or "").startswith("http"):
                    self.known.add(pid)
                    self._attach(p)
                    return True
            time.sleep(0.7)
        return False

    def js(self, expr):
        return self.s.eval(expr)

    # -- finding / clicking by DOM text --------------------------------------
    def find_text(self, text, exact=True):
        """Center of the SMALLEST visible element whose innerText matches. Returns
        {x,y,w,h} in viewport CSS px (== CDP input coords) or None."""
        return self.js("""(()=>{const T=%s, EX=%s;
 const cs=[];
 for (const e of document.querySelectorAll('*')) {
   const r = e.getBoundingClientRect();
   if (r.width < 2 || r.height < 2) continue;
   const t = ((e.innerText || '') + '').trim();
   if (!t) continue;
   if (EX ? t === T : t.includes(T)) cs.push({r: r, a: r.width * r.height});
 }
 cs.sort((a, b) => a.a - b.a);
 if (!cs.length) return null;
 const r = cs[0].r;
 return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
         w: Math.round(r.width), h: Math.round(r.height)};})()"""
                       % (_js_str(text), "true" if exact else "false"))

    def find_card(self, text, min_h=60):
        """Center of the clickable CARD containing the text (e.g. the 用于4*7相纸 canvas
        box in the 创建设计 modal): first ancestor taller than min_h px."""
        return self.js("""(()=>{const T=%s;
 let leaf = null;
 for (const e of document.querySelectorAll('*')) {
   if (e.children.length) continue;
   const t = ((e.innerText || '') + '').trim();
   if (!t.includes(T)) continue;
   const r = e.getBoundingClientRect();
   if (r.width < 2) continue;
   leaf = e; break;
 }
 if (!leaf) return null;
 let p = leaf;
 for (let i = 0; i < 6 && p; i++) {
   const r = p.getBoundingClientRect();
   if (r.height > %d && r.width > 60)
     return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};
   p = p.parentElement;
 }
 const r = leaf.getBoundingClientRect();
 return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)};})()"""
                       % (_js_str(text), min_h))

    def click_xy(self, x, y, settle=1.0):
        for typ, extra in (("mouseMoved", {}),
                           ("mousePressed", {"button": "left", "clickCount": 1}),
                           ("mouseReleased", {"button": "left", "clickCount": 1})):
            self.s.cmd("Input.dispatchMouseEvent", type=typ, x=x, y=y, **extra)
            time.sleep(0.05)
        time.sleep(settle)

    def click_text(self, text, exact=True, settle=1.2):
        p = self.find_text(text, exact)
        if not p:
            return False
        self.click_xy(p["x"], p["y"], settle)
        return True

    def wait_text(self, text, timeout=12.0, exact=True):
        t0 = time.time()
        while time.time() - t0 < timeout:
            p = self.find_text(text, exact)
            if p:
                return p
            time.sleep(0.6)
        return None

    def texts(self, max_items=100):
        """Short visible leaf texts — the step-failure dump for calibration."""
        return self.js("""(()=>{const out=[], seen=new Set();
 for (const e of document.querySelectorAll('*')) {
   if (e.children.length) continue;
   const r = e.getBoundingClientRect();
   if (r.width < 2 || r.height < 2) continue;
   const t = ((e.innerText || e.value || '') + '').trim();
   if (t && t.length <= 18 && !seen.has(t)) { seen.add(t); out.push(t); }
   if (out.length >= %d) break;
 }
 return out;})()""" % max_items)

    # -- keyboard -------------------------------------------------------------
    def key(self, key, code, vk, text=None, modifiers=0):
        down = dict(type="keyDown", key=key, code=code, windowsVirtualKeyCode=vk,
                    nativeVirtualKeyCode=vk, modifiers=modifiers)
        if text:
            down["text"] = text
        self.s.cmd("Input.dispatchKeyEvent", **down)
        time.sleep(0.04)
        self.s.cmd("Input.dispatchKeyEvent", type="keyUp", key=key, code=code,
                   windowsVirtualKeyCode=vk, nativeVirtualKeyCode=vk, modifiers=modifiers)
        time.sleep(0.1)

    def esc(self):
        self.key("Escape", "Escape", 27)

    def enter(self):
        self.key("Enter", "Enter", 13, text="\r")

    def select_all(self):
        self.key("a", "KeyA", 65, modifiers=2)   # 2 == Ctrl

    def insert_text(self, s):
        self.s.cmd("Input.insertText", text=str(s))
        time.sleep(0.15)

    # -- 高级 W/H/X/Y fields ---------------------------------------------------
    def field_by_label(self, label):
        """The 高级 panel labels its inputs W/H/X/Y — find the <input> nearest a label."""
        return self.js("""(()=>{const L=%s;
 let lab = null;
 for (const e of document.querySelectorAll('*')) {
   if (e.children.length) continue;
   if (((e.innerText || '') + '').trim() !== L) continue;
   const r = e.getBoundingClientRect();
   if (r.width < 1) continue;
   lab = e; break;
 }
 if (!lab) return null;
 let p = lab;
 for (let i = 0; i < 5 && p; i++) {
   p = p.parentElement;
   const inp = p && p.querySelector('input');
   if (inp) {
     const r = inp.getBoundingClientRect();
     return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
             v: inp.value};
   }
 }
 return null;})()""" % _js_str(label))

    def set_field(self, label, value):
        f = self.field_by_label(label)
        if not f:
            log(f"WARN: field {label!r} not found")
            return False
        self.click_xy(f["x"], f["y"], 0.4)
        self.select_all()
        self.insert_text(value)
        self.enter()
        time.sleep(0.5)
        return True

    # -- upload ----------------------------------------------------------------
    def upload_file(self, path):
        """Click 上传图片 with the page's file chooser intercepted, then feed the file
        straight to the chooser's input node — no native dialog ever opens."""
        self.s.cmd("Page.setInterceptFileChooserDialog", enabled=True)
        try:
            if not self.click_text("上传图片"):
                log("ERROR: 上传图片 button not found")
                return False
            ev = self.s.wait_event("Page.fileChooserOpened", timeout=10.0)
            if ev:
                node = ev.get("params", {}).get("backendNodeId")
                self.s.cmd("DOM.setFileInputFiles", files=[path], backendNodeId=node)
                log("file fed via fileChooser interception")
                return True
            log("no fileChooserOpened event; trying a hidden input[type=file]")
            if self.js("document.querySelectorAll('input[type=file]').length"):
                root = self.s.cmd("DOM.getDocument")["root"]["nodeId"]
                q = self.s.cmd("DOM.querySelector", nodeId=root,
                               selector="input[type=file]")
                if q.get("nodeId"):
                    self.s.cmd("DOM.setFileInputFiles", files=[path], nodeId=q["nodeId"])
                    log("file fed via hidden input[type=file]")
                    return True
            log("ERROR: no file chooser and no input[type=file] — the app may use a "
                "JS-bridge native picker; send the snaps + console")
            return False
        finally:
            try:
                self.s.cmd("Page.setInterceptFileChooserDialog", enabled=False)
            except Exception:  # noqa: BLE001
                pass

    # -- screenshots -------------------------------------------------------------
    def snap(self, tag):
        import base64
        path = os.path.join(LOGS_DIR, f"cal_{len(SNAPS):02d}_{tag}.png")
        try:
            data = self.s.cmd("Page.captureScreenshot", format="png").get("data", "")
            with open(path, "wb") as fh:
                fh.write(base64.b64decode(data))
            SNAPS.append((tag, path))
            log(f"snap -> {path}")
        except Exception as e:  # noqa: BLE001
            log(f"(snap {tag} failed: {e})")


# ---- the HYBRID print flow (CDP for web home, SendInput for Flutter UI) -----------
# Window-relative offsets for the FLUTTER surfaces, measured off OS screenshots
# (window origin from pygetwindow; calibrated at the standard 1296x768 window, 100% DPI).
ED = {
    "ft_4x7_box":        (526, 305),  # 创建设计 modal: 用于4*7相纸 box (VERIFIED by fluttertest)
    "ed_upload_tool":    (41, 262),   # editor left toolbar: 上传 (VERIFIED 2026-07-06)
    "ed_upload_img_btn": (242, 105),  # upload panel: teal 上传图片 -> native file dialog
    "ed_lib_thumb1":     (163, 387),  # upload panel: first 原图 library thumbnail
    "ed_apply_btn":      (648, 656),  # 效果图 modal: teal 应用 (place original) — VERIFIED loc
    "ed_aicutout_btn":   (648, 570),  # 效果图 modal: AI抠图 (die-cut; metered "Free now")
    "ed_effect_close":   (820, 104),  # 效果图 modal: close ✕
    "fld_w":             (1099, 516), # 高级(mm) W field (VERIFIED cal_06_placed)
    "fld_h":             (1193, 516), # 高级(mm) H field
    "fld_x":             (1099, 556), # 高级(mm) X field
    "fld_y":             (1193, 556), # 高级(mm) Y field
    "ed_make_btn":       (1243, 52),  # editor top-right: teal 制作 (VERIFIED, pale teal)
}
ED_APPLY_REGION = (560, 630, 900, 685)    # rel region of the teal 应用 (效果图 modal bottom)
# The 高级 panel is in MILLIMETRES on Windows (mac used inches). 4x7in canvas = 101.6 x 177.8 mm.
CANVAS_W_MM, CANVAS_H_MM = 101.6, 177.8
ED_MAKE_REGION = (1150, 30, 1290, 75)     # rel region of the teal 制作 button
ED_UPLOAD_REGION = (100, 84, 410, 126)    # rel region of the teal 上传图片 button
                                          # (btn is rel ~(101,89)-(385,122), center (243,105))
ED_CANVAS = (603, 172, 872, 679)          # rel rect of the white 4x7 canvas


def canvas_has_object(img, ox, oy, min_px=150):
    """True if the canvas rect contains enough non-white pixels (a placed object)."""
    px = img.load()
    cnt = 0
    for y in range(oy + ED_CANVAS[1] + 8, oy + ED_CANVAS[3] - 8, 3):
        for x in range(ox + ED_CANVAS[0] + 8, ox + ED_CANVAS[2] - 8, 3):
            r, g, b = px[x, y]
            if min(r, g, b) < 235:
                cnt += 1
                if cnt >= min_px:
                    return True
    return False


def find_teal_px(img, x0, y0, x1, y1, min_px=40, pale_ok=False):
    """Teal-accent detector on an OS screenshot (absolute px, scale 1.0). Returns the
    cluster centroid or None. pale_ok also accepts the washed-out/disabled teal the
    制作 button shows over an empty canvas."""
    px = img.load()
    pts = []
    for y in range(max(0, int(y0)), min(img.height, int(y1)), 2):
        for x in range(max(0, int(x0)), min(img.width, int(x1)), 2):
            r, g, b = px[x, y]
            if pale_ok:
                hit = g > 160 and b > 160 and r < 200 and (g - r) > 25 and abs(g - b) < 65
            else:
                hit = g > 165 and b > 155 and r < 155 and (g - r) > 35 and abs(g - b) < 65
            if hit:
                pts.append((x, y))
    if len(pts) < min_px:
        return None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return cx, cy


def os_snap(pg, tag):
    """Full-screen OS screenshot into the cal_NN series (captures Flutter UI, which CDP
    screenshots cannot). Returns the RGB image for vision checks."""
    path = os.path.join(LOGS_DIR, f"cal_{len(SNAPS):02d}_{tag}.png")
    img = pg.screenshot()
    img.save(path)
    SNAPS.append((tag, path))
    log(f"snap -> {path}")
    return img.convert("RGB")


def set_num_field(pg, gw, ox, oy, rel, value):
    """Set a Flutter numeric field. A single click only placed the caret (the value never
    changed: 22.9 stayed 22.9), so: bring the window forward, DOUBLE-CLICK the field to enter
    edit mode + select its number, then Ctrl+A + Delete to clear, typewrite the new digits
    (pure ASCII digits/'.' — no IME involvement), and Enter to commit."""
    win = find_liene_window(gw)
    if win is not None:
        try:
            win.activate()
        except Exception:  # noqa: BLE001
            pass
    time.sleep(0.2)
    x, y = ox + rel[0], oy + rel[1]
    _send_dblclick(x, y)
    time.sleep(0.3)
    pg.hotkey("ctrl", "a")
    time.sleep(0.15)
    pg.press("delete")
    time.sleep(0.15)
    pg.typewrite(str(value), interval=0.06)
    time.sleep(0.2)
    pg.press("enter")
    time.sleep(0.6)


def wait_file_dialog(gw, appear=True, timeout=10.0):
    """Wait for the native open dialog (title 打开/Open) to appear/disappear."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        titles = [t.strip() for t in gw.getAllTitles() if t.strip()]
        found = any(t == "打开" or t.startswith("打开") or t == "Open" for t in titles)
        if found == appear:
            return True
        time.sleep(0.5)
    return False


def hybrid_flow(image, dry_run=True):
    """Home (CDP) -> 创建设计 modal -> 4x7 editor -> upload panel -> feed file -> place
    thumbnail -> 制作 -> 切割预览 (SendInput for all Flutter UI). CURRENT CHECKPOINT 2:
    stops at the preview WITHOUT clicking anything inside it — its 切割 offset, the
    sizing controls and the dry-run close get calibrated from this run's screenshots."""
    _require_win()
    _dpi_aware()
    pg, gw, clip, _Image = _deps()
    image = os.path.abspath(image)
    if not os.path.exists(image):
        sys.exit(f"ERROR: image not found: {image}")
    clear_snaps()

    def done(ok):
        log("=" * 60)
        log(("CHECKPOINT REACHED" if ok else "FAILED") + " — calibration build; the "
            "remaining steps get wired from these snaps.")
        log(f"{len(SNAPS)} step screenshots:")
        for tag, path in SNAPS:
            log(f"  {path}")
        log("-> send me ALL logs\\cal_*.png plus this console output.")
        return ok

    # 1. ALWAYS restart the app first. The home webview stays alive in CDP even when an
    #    editor tab covers it, so DOM checks can't tell which tab is VISIBLE — a restart
    #    guarantees: home tab active, zero leftover 画板 tabs, debug port on.
    log("restarting the app for a guaranteed-clean home state...")
    restart_liene_with_cdp()
    cui = CdpUI()
    if not cui.wait_text("画板", timeout=25):
        log(f"ERROR: home never appeared; texts: {cui.texts()}")
        return done(False)
    time.sleep(1.5)                       # let the home tab finish rendering
    win = find_liene_window(gw)
    if win is None:
        sys.exit("ERROR: Liene window not found")
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(0.6)
    except Exception:  # noqa: BLE001
        pass
    ox, oy = win.left, win.top
    log(f"window @({ox},{oy}) {win.width}x{win.height}")
    os_snap(pg, "home")

    # 2. 画板 (CDP) -> Flutter 创建设计 modal
    p = cui.find_text("画板")
    cui.click_xy(p["x"], p["y"], 2.0)
    os_snap(pg, "create_modal")

    # 3. 用于4*7相纸 box (SendInput on Flutter) -> editor. Poll for the 制作 button
    #    (pale/disabled teal over an empty canvas) — first editor open can be slow.
    _send_click(ox + ED["ft_4x7_box"][0], oy + ED["ft_4x7_box"][1])
    found = None
    for _ in range(6):
        time.sleep(2.5)
        img = pg.screenshot().convert("RGB")
        found = find_teal_px(img, ox + ED_MAKE_REGION[0], oy + ED_MAKE_REGION[1],
                             ox + ED_MAKE_REGION[2], oy + ED_MAKE_REGION[3], pale_ok=True)
        if found:
            break
    os_snap(pg, "editor")
    if not found:
        log("ERROR: editor did not open (teal 制作 not found top-right after ~15s)")
        return done(False)
    log("editor open (制作 button detected)")

    # 4. 上传 tool -> in-app upload panel (teal 上传图片 button at its top verifies it).
    #    Poll: the panel slides in and its images can take a moment to paint.
    _send_click(ox + ED["ed_upload_tool"][0], oy + ED["ed_upload_tool"][1])
    panel = None
    for _ in range(5):
        time.sleep(1.2)
        img = pg.screenshot().convert("RGB")
        panel = find_teal_px(img, ox + ED_UPLOAD_REGION[0], oy + ED_UPLOAD_REGION[1],
                             ox + ED_UPLOAD_REGION[2], oy + ED_UPLOAD_REGION[3])
        if panel:
            break
    os_snap(pg, "upload_panel")
    if not panel:
        log("ERROR: upload panel did not open (teal 上传图片 not found)")
        return done(False)

    # 5. 上传图片 -> NOW the native file dialog opens; feed the path by keyboard
    _send_click(ox + ED["ed_upload_img_btn"][0], oy + ED["ed_upload_img_btn"][1])
    if not wait_file_dialog(gw, appear=True, timeout=10.0):
        os_snap(pg, "FAIL_no_file_dialog")
        log("ERROR: file dialog did not appear after clicking 上传图片")
        return done(False)
    os_snap(pg, "file_dialog")
    clip.copy(image)
    time.sleep(0.2)
    pg.hotkey("alt", "n")
    time.sleep(0.3)
    pg.hotkey("ctrl", "a")
    time.sleep(0.2)
    pg.hotkey("ctrl", "v")
    time.sleep(0.4)
    pg.press("enter")
    if not wait_file_dialog(gw, appear=False, timeout=12.0):
        os_snap(pg, "FAIL_dialog_stuck")
        log("ERROR: the open dialog did not close (path paste may have failed)")
        return done(False)
    time.sleep(3.5)                        # upload/processing

    # 6. the upload AUTO-OPENS a 效果图 modal (image preview + 应用 / AI抠图). Click the
    #    teal 应用 to place the ORIGINAL onto the canvas (AI抠图 = die-cut, metered; skipped
    #    during calibration). The modal covers the canvas, so poll for its teal 应用 button.
    apply = None
    for _ in range(8):
        time.sleep(1.2)
        img = pg.screenshot().convert("RGB")
        apply = find_teal_px(img, ox + ED_APPLY_REGION[0], oy + ED_APPLY_REGION[1],
                             ox + ED_APPLY_REGION[2], oy + ED_APPLY_REGION[3])
        if apply:
            break
    os_snap(pg, "effect_modal")
    if apply:
        _send_click(int(apply[0]), int(apply[1]))   # centroid is absolute px (scale 1.0)
    else:
        log("WARN: teal 应用 not found in the 效果图 modal region; using offset fallback")
        _send_click(ox + ED["ed_apply_btn"][0], oy + ED["ed_apply_btn"][1])
    time.sleep(2.5)
    img = os_snap(pg, "placed")
    if not canvas_has_object(img, ox, oy):
        log("WARN: canvas looks empty after 应用 — placement may have missed")
    else:
        log("image placed on the canvas")

    # 6.5 fit + center via the 高级(mm) fields, same math as macOS fit_and_center but in mm
    #     (Windows panel is mm). Object is selected after 应用, so the fields are live.
    from PIL import Image as PILImage
    iw, ih = PILImage.open(image).size
    aspect = iw / ih
    W = min(CANVAS_W_MM, CANVAS_H_MM * aspect)
    H = W / aspect
    X = (CANVAS_W_MM - W) / 2
    Y = (CANVAS_H_MM - H) / 2
    W, H, X, Y = round(W, 1), round(H, 1), round(X, 1), round(Y, 1)
    log(f"fit(mm): aspect={aspect:.3f} -> W={W} H={H} X={X} Y={Y}")
    set_num_field(pg, gw, ox, oy, ED["fld_w"], W)
    set_num_field(pg, gw, ox, oy, ED["fld_h"], H)
    set_num_field(pg, gw, ox, oy, ED["fld_x"], X)
    set_num_field(pg, gw, ox, oy, ED["fld_y"], Y)
    time.sleep(5.0)            # fixed wait for the resize to re-render
    os_snap(pg, "after_fit")   # verify the four fields took the values (read them next round)

    # 7. 制作 -> 切割预览. Fixed 5s wait for the loading, then snap (per user: the color-based
    #    loading detector was unreliable; a hardcoded wait is what they want here). SNAP ONLY —
    #    nothing in the preview is clicked (the 切割 offset gets measured from this snap).
    _send_click(ox + ED["ed_make_btn"][0], oy + ED["ed_make_btn"][1])
    time.sleep(5.0)
    os_snap(pg, "cut_preview")
    log("CHECKPOINT 3 reached — uploaded, placed via 应用, fit W/H/X/Y (mm), 制作 clicked, "
        "waited 5s, preview snapped, NOTHING in the preview clicked (no ribbon).")
    return done(True)


# ---- create-canvas diagnostics --------------------------------------------------
# First CDP dryrun: clicking 画板 succeeded but NO 创建设计 modal appeared in the DOM
# (home texts unchanged). Candidate explanations: (a) the modal opens in a NEW webview,
# (b) the modal is native Flutter UI triggered via hanntoJsBridge (CDP can't see it, but
# we could call the bridge directly), (c) the in-page click didn't trigger the handler.
# These two commands separate the cases in one round trip.

def _dump_bridge(ui):
    names = ui.js("Object.getOwnPropertyNames(window)"
                  ".filter(k=>/bridge|hannto|flutter|native|jiyin/i.test(k))")
    log(f"bridge-ish globals: {names}")
    for obj in (names or []):
        t = ui.js(f"typeof window[{_js_str(obj)}]")
        keys = ui.js(
            "(()=>{try{const o=window[%s]; if(!o) return null; const ks=new Set();"
            " for(const k in o) ks.add(k);"
            " Object.getOwnPropertyNames(o).forEach(k=>ks.add(k));"
            " const pr=Object.getPrototypeOf(o);"
            " if(pr) Object.getOwnPropertyNames(pr).forEach(k=>ks.add(k));"
            " return [...ks];}catch(e){return String(e)}})()" % _js_str(obj))
        log(f"  window.{obj}: typeof={t} keys={keys}")


def canvasprobe():
    """Click 画板 over CDP and collect evidence about what (if anything) opens:
    new CDP targets, DOM texts, a CDP snap AND an OS-level screenshot (a native Flutter
    modal shows only in the latter). Also enumerates the hanntoJsBridge surface."""
    _require_win()
    _dpi_aware()
    ui = CdpUI()
    clear_snaps()
    _dump_bridge(ui)
    p = ui.find_text("画板")
    log(f"画板 element rect: {p}")
    before = {t.get("id") for t in cdp_pages(timeout=3.0)}
    ui.snap("before_huaban")
    if p:
        ui.click_xy(p["x"], p["y"], 2.5)
    else:
        log("WARN: 画板 not found in DOM")
    after = cdp_pages(timeout=3.0)
    log("CDP targets after the click:")
    for t in after:
        mark = "NEW  " if t.get("id") not in before else "     "
        log(f"  {mark}title={t.get('title')!r} url={t.get('url')!r}")
    log(f"DOM texts now: {ui.texts(40)}")
    ui.snap("after_huaban_dom")
    try:
        pg, _gw, _clip, _Image = _deps()
        osshot = os.path.join(LOGS_DIR, "cal_os_after_huaban.png")
        pg.screenshot().save(osshot)
        log(f"OS screenshot -> {osshot}  (shows native/Flutter overlays that CDP can't)")
    except Exception as e:  # noqa: BLE001
        log(f"(OS screenshot failed: {e})")
    log("-> send console output + ALL logs\\cal_*.png")


def fluttertest():
    """canvasprobe proved: the CDP click on 画板 WORKS and the 创建设计 modal is NATIVE
    FLUTTER UI (visible in the OS screenshot, absent from the DOM). clicktest only ever
    aimed OS-injected clicks at WEB elements — the drop may live in the Flutter->webview
    input forwarding, not at the Flutter window itself. So: open the modal via CDP, then
    SendInput-click the Flutter 用于4*7相纸 box and see whether an editor webview appears."""
    _require_win()
    _dpi_aware()
    pg, gw, _clip, _Image = _deps()
    win = find_liene_window(gw)
    if win is None:
        sys.exit("ERROR: Liene window not found")
    try:
        if win.isMinimized:
            win.restore()
        win.activate()
        time.sleep(0.8)
    except Exception:  # noqa: BLE001
        pass
    ui = CdpUI()
    clear_snaps()
    if not ui.find_text("画板"):
        sys.exit("not on the home page — run 'cdp' (restarts the app) and retry")
    p = ui.find_text("画板")
    ui.click_xy(p["x"], p["y"], 2.0)          # opens the Flutter 创建设计 modal (proven)
    pg.screenshot().save(os.path.join(LOGS_DIR, "cal_ft_modal.png"))
    before = {t.get("id") for t in cdp_pages(timeout=2.0)}
    # 用于4*7相纸 box: window-rel (526,305), measured off canvasprobe's OS screenshot
    # (box center abs (678,351), window origin (152,46)).
    x, y = win.left + 526, win.top + 305
    log(f"SendInput-clicking the Flutter 4*7 box at ({x},{y})")
    n = _send_click(x, y)
    log(f"  injected {n}/2 events")
    time.sleep(3.5)
    pg.screenshot().save(os.path.join(LOGS_DIR, "cal_ft_after.png"))
    log(f"OS screenshots -> {LOGS_DIR}\\cal_ft_modal.png / cal_ft_after.png")
    after = cdp_pages(timeout=6.0)
    new = [t for t in after if t.get("id") not in before]
    log("CDP targets now:")
    for t in after:
        mark = "NEW  " if t.get("id") not in before else "     "
        log(f"  {mark}title={t.get('title')!r} url={t.get('url')!r}")
    if new:
        log("*** FLUTTER UI ACCEPTS SendInput — hybrid driver unlocked ***")
        for t in new:
            if not (t.get("url") or "").startswith("http"):
                continue
            try:
                s = CdpSession(t["webSocketDebuggerUrl"])
                texts = s.eval("""(()=>{const out=[], seen=new Set();
 for (const e of document.querySelectorAll('*')) {
   if (e.children.length) continue;
   const r = e.getBoundingClientRect();
   if (r.width < 2 || r.height < 2) continue;
   const t = ((e.innerText || e.value || '') + '').trim();
   if (t && t.length <= 18 && !seen.has(t)) { seen.add(t); out.push(t); }
   if (out.length >= 80) break;
 }
 return out;})()""")
                log(f"  editor texts: {texts}")
                s.close()
            except Exception as e:  # noqa: BLE001
                log(f"  (editor attach failed: {e})")
    else:
        log("no new webview appeared — either SendInput is also blocked for Flutter UI "
            "(next fallback: UIA Invoke via pywinauto) or the box offset missed; "
            "compare cal_ft_modal.png vs cal_ft_after.png (modal still open? box "
            "highlighted?)")
    log("-> send console output + logs\\cal_ft_*.png")


def pages_cmd():
    """List every CDP page target with its URL and visible texts. Run this AFTER manually
    navigating the app into the editor — it reveals where the editor lives (same page?
    new webview? which URL?) and the editor's real button labels."""
    _require_win()
    pages = cdp_pages(timeout=8.0)
    if not pages:
        log("no CDP targets — start the app via the 'cdp' command first")
        return
    log(f"{len(pages)} page target(s):")
    for i, t in enumerate(pages):
        log(f"  [{i}] title={t.get('title')!r} url={t.get('url')!r}")
        if not (t.get("url") or "").startswith("http"):
            continue
        try:
            s = CdpSession(t["webSocketDebuggerUrl"])
            texts = s.eval("""(()=>{const out=[], seen=new Set();
 for (const e of document.querySelectorAll('*')) {
   if (e.children.length) continue;
   const r = e.getBoundingClientRect();
   if (r.width < 2 || r.height < 2) continue;
   const t = ((e.innerText || e.value || '') + '').trim();
   if (t && t.length <= 18 && !seen.has(t)) { seen.add(t); out.push(t); }
   if (out.length >= 60) break;
 }
 return out;})()""")
            log(f"      texts: {texts}")
            s.close()
        except Exception as e:  # noqa: BLE001
            log(f"      (attach failed: {e})")
    log("-> send console output.")


# ---- Liene log discovery (job polling) ---------------------------------------
def liene_log_files():
    """Find the Windows Liene app's own liene_photo_pc_*.log files (location unknown a
    priori — the macOS path doesn't apply). Returns newest-first list."""
    bases = [os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", ""),
             os.environ.get("PROGRAMDATA", ""),
             os.path.join(os.environ.get("USERPROFILE", ""), "Documents")]
    hits = []
    for base in [b for b in bases if b and os.path.isdir(b)]:
        for root, dirs, files in os.walk(base):
            depth = root[len(base):].count(os.sep)
            if depth >= 4:
                dirs[:] = []
                continue
            low = os.path.basename(root).lower()
            if not any(h in low for h in ("liene", "hannto", "jiyin", "photomacos", "photo_pc")):
                continue
            for f in files:
                if f.lower().endswith(".log"):
                    hits.append(os.path.join(root, f))
            dirs[:] = []   # matched dir: don't descend further from the walk side
            hits.extend(glob.glob(os.path.join(root, "**", "*.log"), recursive=True))
    noise = ("webview2", "ebwebview", "leveldb")   # WebView2 browser-profile DB logs, not app logs
    hits = [f for f in set(hits) if not any(n in f.lower() for n in noise)]
    return sorted(hits, key=lambda f: os.path.getmtime(f), reverse=True)


def logscan():
    _require_win()
    log("scanning for Liene app logs (AppData/ProgramData/Documents)...")
    hits = liene_log_files()
    if not hits:
        log("no Liene .log files found — job polling will be skipped on real prints")
    for f in hits[:20]:
        log(f"  {f}  ({os.path.getsize(f)//1024} KB, "
            f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(f)))})")
    return hits


def wait_done(timeout=300):
    # Prefer the stdout capture from our own relaunch (the Windows app has no on-disk
    # log like macOS; [REQ]/[RESP] device traffic only goes to stdout).
    if os.path.exists(APP_LOG) and time.time() - os.path.getmtime(APP_LOG) < 6 * 3600:
        logf = APP_LOG
    else:
        files = [f for f in liene_log_files()
                 if "liene_photo" in os.path.basename(f).lower()]
        if not files:
            log("WARN: no app log found; cannot poll completion")
            return None
        logf = files[0]
    log(f"polling {logf}")
    start = time.time()
    last = ""
    while time.time() - start < timeout:
        try:
            with open(logf, "rb") as fh:
                fh.seek(max(0, os.path.getsize(logf) - 262144))
                tail = fh.read().decode("utf-8", "ignore")
        except OSError:
            time.sleep(4)
            continue
        ms = re.findall(r'"job-state":(\d+).*?"job-sub-state":(\d+)', tail)
        rib = re.findall(r'"ribbon-cnt":(\d+)', tail)
        if ms:
            st, sub = ms[-1]
            cur = f'state={st}/{sub} ribbon={rib[-1] if rib else "?"}'
            if cur != last:
                log("  " + cur)
                last = cur
            if st == "9":
                log("DONE — job completed.")
                return True
        time.sleep(4)
    log("WARN: timed out waiting for completion")
    return False


# ---- CLI ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Windows Liene-app UI automation (PixCut S1).")
    ap.add_argument("command",
                    choices=["probe", "clicktest", "cdp", "canvasprobe", "fluttertest",
                             "pages", "dryrun", "print", "logscan"],
                    help="probe = geometry report; clicktest = diagnose click injection; "
                         "cdp = restart app with WebView2 remote debugging + DOM probe; "
                         "canvasprobe = click 画板 + collect evidence of what opens; "
                         "pages = list all CDP targets + their texts (run in the editor); "
                         "dryrun = full flow WITHOUT printing (saves step screenshots); "
                         "logscan = find the app's log files; "
                         "print = real print (disabled until calibrated)")
    ap.add_argument("image", nargs="?", help="image file (dryrun/print)")
    ap.add_argument("--margin", type=float, default=0.0,
                    help="shrink the fitted image by this margin (inches) per side")
    args = ap.parse_args()
    _require_win()

    if args.command == "probe":
        probe()
    elif args.command == "clicktest":
        clicktest()
    elif args.command == "cdp":
        cdp()
    elif args.command == "canvasprobe":
        canvasprobe()
    elif args.command == "fluttertest":
        fluttertest()
    elif args.command == "pages":
        pages_cmd()
    elif args.command == "logscan":
        logscan()
    elif args.command == "dryrun":
        if not args.image:
            sys.exit("usage: pixcut_win.py dryrun <image>  "
                     "(e.g. pixcut-probe\\samples\\sample_4x7.jpg)")
        hybrid_flow(args.image, dry_run=True)
    elif args.command == "print":
        if not CALIBRATED:
            sys.exit("REFUSING to print: the Windows flow is not calibrated yet "
                     "(CALIBRATED=False). Run 'dryrun' first and send back the "
                     "cal_*.png screenshots; printing consumes ribbon.")
        if not args.image:
            sys.exit("usage: pixcut_win.py print <image>")
        hybrid_flow(args.image, dry_run=False)


if __name__ == "__main__":
    main()
