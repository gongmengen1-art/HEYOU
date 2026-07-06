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

CALIBRATION STATE (probe run 2026-07-06, screen 1600x900 @100%, window 1296x768@(152,46)):
  * The Windows app is the SAME Creativerse web UI as macOS at nearly the same client size
    (mac 1280x760): the web-content offsets transfer ~1:1 (measured: + 画板 mac (1103,55)
    vs win (1101,55)). Native title bar differs (home_btn re-measured for Windows).
  * Offsets marked "mac guess" below are unverified — the `dryrun` command snapshots every
    step to logs\cal_NN_<step>.png so they can be corrected from one run's screenshots.

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

# Per-control offsets in *physical pixels*, relative to the Liene window's top-left
# (pygetwindow win.left/win.top). "measured" = read off the 2026-07-06 Windows probe
# screenshot; "mac guess" = ported verbatim from print_via_app.py (same web UI, verify
# via dryrun snapshots).
OFF: dict[str, tuple[int, int]] = {
    "home_btn":      (133, 16),    # measured: 🏠首页 in the native title bar
    "huaban_btn":    (1101, 55),   # measured: teal "+ 画板" on Home (also teal-detected)
    "blank_plus":    (517, 305),   # mac guess: 创建设计 modal, "+" 用于4*7相纸 box
    "upload_tool":   (34, 261),    # mac guess: left toolbar 上传
    "upload_btn":    (234, 97),    # mac guess: teal 上传图片 at the upload panel top
    "apply_btn":     (640, 645),   # mac guess: teal 应用 in the 效果图 modal
    "ai_cutout":     (1157, 717),  # mac guess: right panel 工具 > AI抠图
    "next_btn":      (643, 656),   # mac guess: teal 下一步 in the AI抠图 modal
    "fld_w":         (1092, 508),  # mac guess: 高级 W field
    "fld_h":         (1185, 508),  # mac guess: 高级 H field
    "fld_x":         (1092, 548),  # mac guess: 高级 X field
    "fld_y":         (1185, 548),  # mac guess: 高级 Y field
    "make_btn":      (1235, 52),   # mac guess: pale-teal 制作 (top-right 2nd row)
    "cut_btn":       (840, 592),   # mac guess: teal 切割 in 切割预览 — PRINTS, dryrun never clicks
    "cut_preview_x": (759, 120),   # mac guess: ✕ of the 切割预览 modal
}

# Window-relative rects (x0,y0,x1,y1) used by the teal detector / vision, ported from macOS.
RECT_HUABAN = (980, 35, 1290, 80)      # home: teal + 画板 button row
RECT_UPLOAD = (10, 80, 440, 125)       # editor: teal 上传图片 at upload-panel top
RECT_MODAL_BOTTOM = (300, 560, 980, 700)   # 效果图 / AI抠图 modal: teal 应用 / 下一步
RECT_CUT = (620, 560, 1020, 660)       # 切割预览: teal 切割 button
RECT_CANVAS = (255, 95, 1005, 710)     # editor canvas viewport (object detection)


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

    def abs(self, name):
        dx, dy = OFF[name]
        return self.ox + dx, self.oy + dy

    def click_pt(self, x, y, settle=0.6):
        self.activate()
        n = _send_click(int(x), int(y))
        if n != 2:
            log(f"WARN: SendInput injected {n}/2 events at ({int(x)},{int(y)}); "
                "falling back to pyautogui")
            self._pg.click(int(x), int(y))
        time.sleep(settle)

    def click(self, name, settle=0.8):
        x, y = self.abs(name)
        self.click_pt(x, y, settle)

    def hotkey(self, *keys):
        self._pg.hotkey(*keys)
        time.sleep(0.15)

    def press(self, key):
        self._pg.press(key)
        time.sleep(0.15)

    def esc(self):
        self.press("esc")
        time.sleep(0.3)

    def clip_set(self, text):
        self._clip.copy(str(text))

    def clip_get(self):
        return self._clip.paste()

    def paste_text(self, text):
        """Type text IME-safely: put it on the clipboard and Ctrl+V."""
        self.clip_set(text)
        time.sleep(0.15)
        self.hotkey("ctrl", "v")
        time.sleep(0.2)

    def type_field(self, name, value):
        """Click a field, select-all, paste the value, Enter."""
        x, y = self.abs(name)
        self.click_pt(x, y, 0.4)
        self.hotkey("ctrl", "a")
        self.paste_text(value)
        self.press("enter")
        time.sleep(0.5)

    def read_field(self, name):
        """Click a field, select-all + copy, return the clipboard text (its value)."""
        x, y = self.abs(name)
        self.click_pt(x, y, 0.4)
        sentinel = "«pixcut-sentinel»"       # no NULs — Windows clipboard truncates at \x00
        self.clip_set(sentinel)
        self.hotkey("ctrl", "a")
        self.hotkey("ctrl", "c")
        time.sleep(0.25)
        val = self.clip_get() or ""
        return "" if val == sentinel else val.strip()

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

    def rect_abs(self, rect):
        """Window-relative (x0,y0,x1,y1) -> absolute points rect."""
        x0, y0, x1, y1 = rect
        return self.ox + x0, self.oy + y0, self.ox + x1, self.oy + y1


def find_teal(img, ui, x0, y0, x1, y1, pick="bottom", min_px=40):
    """Teal accent button inside the points-rect (x0,y0)-(x1,y1). Same detector as macOS.
    Requires at least `min_px` matching samples so stray anti-aliased edges don't register."""
    px = img.load()
    X0, Y0 = ui.pt2px(x0, y0)
    X1, Y1 = ui.pt2px(x1, y1)
    pts = []
    for y in range(max(0, int(Y0)), min(img.height, int(Y1)), 2):
        for x in range(max(0, int(X0)), min(img.width, int(X1)), 2):
            r, g, b = px[x, y]
            if g > 165 and b > 155 and r < 155 and (g - r) > 35 and abs(g - b) < 65:
                pts.append((x, y))
    if len(pts) < min_px:
        return None
    if pick == "bottom":
        ymax = max(p[1] for p in pts)
        pts = [p for p in pts if p[1] > ymax - 80]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return ui.px2pt(cx, cy)


def object_bbox_px(img, ui, region_px, cyan_only=False):
    """Bounding box (PIXELS) of a placed object inside region_px=(x0,y0,x1,y1)."""
    px = img.load()
    x0, y0, x1, y1 = region_px
    xs, ys = [], []
    for y in range(int(y0), int(y1), 2):
        for x in range(int(x0), int(x1), 2):
            r, g, b = px[x, y]
            if cyan_only:
                if g > 185 and b > 195 and r < 130 and (b - r) > 80:
                    xs.append(x); ys.append(y)
            else:
                if min(r, g, b) < 233:
                    xs.append(x); ys.append(y)
    if len(xs) < 20:
        return None
    return min(xs), min(ys), max(xs), max(ys)


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


def snap(ui, tag):
    path = os.path.join(LOGS_DIR, f"cal_{len(SNAPS):02d}_{tag}.png")
    ui.shot(path)
    SNAPS.append((tag, path))
    log(f"snap -> {path}")


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


# ---- high-level steps (ported from print_via_app.py) --------------------------
def on_home(ui, img=None):
    """Home page shows the teal + 画板 button top-right; the editor doesn't."""
    if img is None:
        img = ui.shot()
    return find_teal(img, ui, *ui.rect_abs(RECT_HUABAN), pick="any")


def go_home(ui):
    """Back to the Creativerse home page from anywhere. Click twice — the 1st click may only
    dismiss an overlay (e.g. 任务队列), the 2nd navigates. Idempotent once on home."""
    for _ in range(2):
        ui.click("home_btn", settle=1.3)


def go_fresh(ui):
    """Home -> + 画板 -> 创建设计 -> blank 4x7 canvas."""
    log("navigating Home -> blank 4x7 canvas")
    p = on_home(ui)
    if p:
        ui.click_pt(p[0], p[1], 1.5)
    else:
        ui.click("huaban_btn", settle=1.5)
    snap(ui, "create_modal")
    ui.click("blank_plus", settle=3.0)
    snap(ui, "editor")


def clear_canvas(ui):
    """Delete any object currently on the canvas (so the next image doesn't overlap)."""
    img = ui.shot()
    r = ui.rect_abs(RECT_CANVAS)
    region = (*ui.pt2px(r[0], r[1]), *ui.pt2px(r[2], r[3]))
    bb = object_bbox_px(img, ui, region, cyan_only=False)
    if not bb:
        log("canvas already clear")
        return
    cx, cy = ui.px2pt((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
    top = ui.px2pt(0, bb[1])[1]
    ui.click_pt(cx, cy, 0.7)            # select
    ui.click_pt(cx, top - 49, 0.9)      # floating 🗑 ~49px above the object top
    log("deleted existing object")
    time.sleep(0.5)


def open_upload_panel(ui):
    """Ensure the left 上传 panel is open (clicking the tool toggles it). Detect via the
    teal 上传图片 button at the panel top; re-check AFTER each toggle click."""
    rect = ui.rect_abs(RECT_UPLOAD)
    for _ in range(4):
        if find_teal(ui.shot(), ui, *rect, pick="any"):
            return True
        ui.click("upload_tool", settle=1.3)
        if find_teal(ui.shot(), ui, *rect, pick="any"):
            return True
    return False


def wait_file_dialog(ui, appear=True, timeout=10.0):
    """Wait for the native open dialog (title 打开/Open) to appear/disappear."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        titles = [t.strip() for t in ui._gw.getAllTitles() if t.strip()]
        found = any(t in ("打开", "Open") or t.startswith("打开") for t in titles)
        if found == appear:
            return True
        time.sleep(0.5)
    return False


def upload_image(ui, image_path):
    """Assumes the upload panel is open. Pick the file via the native open dialog and place
    the original onto the canvas (应用). Aborts (returns False) if a stage doesn't verify."""
    img = ui.shot()
    p = find_teal(img, ui, *ui.rect_abs(RECT_UPLOAD), pick="any")
    if p:
        ui.click_pt(p[0], p[1], 1.5)     # teal 上传图片 -> native open dialog
    else:
        ui.click("upload_btn", settle=1.5)
    if not wait_file_dialog(ui, appear=True):
        snap(ui, "FAIL_no_file_dialog")
        log("ERROR: native open dialog did not appear")
        return False
    snap(ui, "file_dialog")
    # Alt+N focuses the 文件名 field (works on zh/en Windows); paste the path, Enter.
    ui.hotkey("alt", "n")
    ui.hotkey("ctrl", "a")
    ui.paste_text(os.path.abspath(image_path))
    ui.press("enter")
    if not wait_file_dialog(ui, appear=False):
        snap(ui, "FAIL_dialog_stuck")
        log("ERROR: open dialog did not close after Enter")
        return False
    time.sleep(2.5)
    snap(ui, "effect_modal")
    # 效果图 modal -> teal 应用 (place original)
    img = ui.shot()
    p = find_teal(img, ui, *ui.rect_abs(RECT_MODAL_BOTTOM), pick="bottom")
    if not p:
        snap(ui, "FAIL_no_apply_btn")
        log("ERROR: 效果图 modal / teal 应用 not found")
        return False
    ui.click_pt(p[0], p[1], 2.0)
    snap(ui, "placed")
    log("image placed (original)")
    return True


def fit_and_center(ui, aspect, margin=0.0):
    """Scale the placed object to fill the 4x7 canvas (no distortion) and center it.
    First VERIFIES the field offsets by reading W back as a number; if that fails the
    offsets are wrong — skip typing (don't feed values into an unknown control)."""
    probe_val = ui.read_field("fld_w")
    try:
        float(probe_val)
    except (ValueError, TypeError):
        snap(ui, "FAIL_fields_unreadable")
        log(f"WARN: 高级 W field read back {probe_val!r} (not a number) — field offsets "
            "need calibration; SKIPPING fit (image keeps its default size)")
        return False
    if not aspect or aspect <= 0:
        log("WARN: unknown aspect; skipping fit")
        return False
    aw = CANVAS_W_IN - 2 * margin
    ah = CANVAS_H_IN - 2 * margin
    W = min(aw, ah * aspect)
    H = W / aspect
    W = round(W, 2); H = round(H, 2)
    X = round((CANVAS_W_IN - W) / 2, 2); Y = round((CANVAS_H_IN - H) / 2, 2)
    log(f"fit: aspect={aspect:.3f} -> {W}x{H}in at ({X},{Y})")
    ui.type_field("fld_w", W)
    ui.type_field("fld_h", H)
    ui.type_field("fld_x", X)
    ui.type_field("fld_y", Y)
    return True


def open_cut_preview(ui):
    ui.click("make_btn", settle=4.5)          # 制作 -> 切割预览 (has a load delay)
    for _ in range(3):
        img = ui.shot()
        if find_teal(img, ui, *ui.rect_abs(RECT_CUT), pick="bottom"):
            snap(ui, "cut_preview")
            return True
        time.sleep(1.5)
    snap(ui, "FAIL_no_cut_preview")
    log("WARN: 切割预览 did not open (制作 may have missed); check make_btn offset")
    return False


def close_cut_preview(ui):
    ui.click("cut_preview_x", settle=0.8)
    ui.esc()
    snap(ui, "after_close")


def do_print(ui):
    """Click 切割 = REAL PRINT, consumes ribbon. Only reachable from the print command."""
    img = ui.shot()
    p = find_teal(img, ui, *ui.rect_abs(RECT_CUT), pick="bottom")
    if p:
        ui.click_pt(p[0], p[1], 1.0)
    else:
        ui.click("cut_btn", settle=1.0)
    log("clicked 切割 — printing")


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
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={CDP_PORT}"
    DETACHED = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    os.makedirs(LOGS_DIR, exist_ok=True)
    logfh = open(APP_LOG, "ab")   # the app keeps the inherited handle after we exit
    subprocess.Popen([exe], cwd=os.path.dirname(exe), env=env, creationflags=DETACHED,
                     stdout=logfh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    logfh.close()
    log(f"relaunched {exe} with --remote-debugging-port={CDP_PORT}")
    log(f"app log captured to {APP_LOG}")


def cdp_pages(timeout=45.0):
    """Poll the CDP HTTP endpoint until page targets appear. Returns the JSON list."""
    import json
    import urllib.request
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=2) as r:
                targets = json.loads(r.read().decode("utf-8"))
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                return pages
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
    return []


class CdpSession:
    """Minimal CDP client over one page's webSocketDebuggerUrl."""

    def __init__(self, ws_url):
        try:
            import websocket
        except ImportError:
            sys.exit("websocket-client missing — run: uv sync")
        self._ws = websocket.create_connection(ws_url, timeout=15)
        self._id = 0

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
            # else: an event — ignore

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
    # pick the Creativerse page (title 'mingshashan' seen on both mac + win)
    pick = next((t for t in pages if "mingshashan" in (t.get("title") or "").lower()),
                pages[0])
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


# ---- flows -------------------------------------------------------------------
def run_flow(image, dry_run=True, margin=0.0, fresh=None):
    """The full print flow. dry_run=True stops at the 切割预览 (NO ribbon)."""
    from PIL import Image as PILImage
    image = os.path.abspath(image)
    if not os.path.exists(image):
        sys.exit(f"ERROR: image not found: {image}")
    ui = make_ui()
    clear_snaps()
    snap(ui, "start")
    ui.esc(); ui.esc()                      # dismiss stray modals from a prior run

    home = on_home(ui)
    if fresh is None:
        fresh = bool(home)                  # auto: on home -> create a fresh canvas
    if fresh:
        if not home:
            go_home(ui)
        go_fresh(ui)
    else:
        clear_canvas(ui)

    if not open_upload_panel(ui):
        snap(ui, "FAIL_upload_panel")
        log("ERROR: upload panel did not open — check upload_tool offset. "
            "Send logs\\cal_*.png")
        return finish(False, dry_run)
    snap(ui, "upload_panel")

    if not upload_image(ui, image):
        return finish(False, dry_run)

    iw, ih = PILImage.open(image).size
    fit_ok = fit_and_center(ui, iw / ih, margin=margin)
    snap(ui, "after_fit")

    prev_ok = open_cut_preview(ui)
    if not prev_ok:
        return finish(False, dry_run)

    if dry_run:
        log("DRY RUN — reached 切割预览; NOT clicking 切割 (no print, no ribbon).")
        close_cut_preview(ui)
        go_home(ui)
        snap(ui, "home_again")
        return finish(True, dry_run, fit_ok=fit_ok)
    do_print(ui)
    wait_done()
    time.sleep(1.0)
    go_home(ui)
    return finish(True, dry_run, fit_ok=fit_ok)


def finish(ok, dry_run, fit_ok=True):
    log("=" * 60)
    log(("DRY-RUN " if dry_run else "PRINT ") + ("COMPLETED" if ok else "FAILED (see FAIL_* snap)"))
    if ok and not fit_ok:
        log("NOTE: fit/center was SKIPPED (field offsets uncalibrated) — the image stayed "
            "at its default small size; that's expected on the first calibration run.")
    log(f"{len(SNAPS)} step screenshots:")
    for tag, path in SNAPS:
        log(f"  {path}")
    log("-> send me ALL logs\\cal_*.png plus this console output.")
    return ok


# ---- CLI ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Windows Liene-app UI automation (PixCut S1).")
    ap.add_argument("command",
                    choices=["probe", "clicktest", "cdp", "dryrun", "print", "logscan"],
                    help="probe = geometry report; clicktest = diagnose click injection; "
                         "cdp = restart app with WebView2 remote debugging + DOM probe; "
                         "dryrun = full flow WITHOUT printing (saves step screenshots); "
                         "logscan = find the app's log files; "
                         "print = real print (disabled until calibrated)")
    ap.add_argument("image", nargs="?", help="image file (dryrun/print)")
    ap.add_argument("--margin", type=float, default=0.0,
                    help="shrink the fitted image by this margin (inches) per side")
    ap.add_argument("--fresh", action="store_true",
                    help="force Home -> new blank 4x7 canvas first (auto-detected otherwise)")
    args = ap.parse_args()
    _require_win()

    if args.command == "probe":
        probe()
    elif args.command == "clicktest":
        clicktest()
    elif args.command == "cdp":
        cdp()
    elif args.command == "logscan":
        logscan()
    elif args.command == "dryrun":
        if not args.image:
            sys.exit("usage: pixcut_win.py dryrun <image>  "
                     "(e.g. pixcut-probe\\samples\\sample_4x7.jpg)")
        run_flow(args.image, dry_run=True, margin=args.margin,
                 fresh=True if args.fresh else None)
    elif args.command == "print":
        if not CALIBRATED:
            sys.exit("REFUSING to print: the Windows flow is not calibrated yet "
                     "(CALIBRATED=False). Run 'dryrun' first and send back the "
                     "cal_*.png screenshots; printing consumes ribbon.")
        if not args.image:
            sys.exit("usage: pixcut_win.py print <image>")
        run_flow(args.image, dry_run=False, margin=args.margin,
                 fresh=True if args.fresh else None)


if __name__ == "__main__":
    main()
