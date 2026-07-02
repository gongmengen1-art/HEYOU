#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pixcut_win.py — Windows port of the macOS Liene-app UI-automation (PixCut S1 printing).

The macOS driver (print_via_app.py) drives the Liene Photo app via osascript / CGEvent /
screencapture. This module does the same on Windows with:
  * pyautogui  — click / move / type / hotkey / screenshot
  * pygetwindow — locate + activate the Liene window, read its rect
  * pyperclip  — clipboard (path paste into the file dialog)
  * psutil     — find / restart the Liene process
The high-level FLOW mirrors print_via_app.py. The per-control OFFSETS below MUST be calibrated
against a Windows screenshot first — window chrome, size and DPI differ from macOS.

STEP 1 (do this first): with the Liene app open, run
    uv run python pixcut-probe\\pixcut_win.py probe
It saves a full-screen screenshot to logs\\pixcut_probe.png and prints the Liene window rect,
DPI/scale and all window titles. Send those to calibrate OFFSETS, then the print flow is enabled.

Status: SCAFFOLDING — `probe` + primitives + vision helpers ready; the print flow is added
once OFFSETS are calibrated from a real Windows screenshot.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

APP_TITLE_HINTS = ("Liene", "极印", "Creativerse", "小蓝盒", "Photo")
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)

# Per-control offsets in *physical pixels*, relative to the Liene window's top-left (win.left,
# win.top). TO BE CALIBRATED from a Windows screenshot — the macOS values do NOT transfer.
OFF: dict[str, tuple[int, int]] = {
    # "home_btn": (x, y), "huaban_tab": (x, y), "make_btn": (x, y), ...  (filled after probe)
}


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
    pyautogui.FAILSAFE = False
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
    logs = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(logs, exist_ok=True)
    shot_path = os.path.join(logs, "pixcut_probe.png")

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
            if any(h.lower() in name.lower() or h.lower() in exe.lower()
                   for h in ("liene", "creativerse", "hannto")):
                cands.append((p.pid, name, exe))
        print(f"[probe] candidate Liene processes: {cands[:10] or 'NONE (name hint miss)'}")
    except Exception as e:  # noqa: BLE001
        print(f"[probe] process scan failed: {e}")

    img = pyautogui.screenshot()
    img.save(shot_path)
    print(f"[probe] screenshot {img.width}x{img.height} saved: {shot_path}")
    print("[probe] DONE — send me logs\\pixcut_probe.png plus everything printed above.")


# ---- input / vision primitives (used by the print flow, added after calibration) ----
class UI:
    """Windows automation primitives, mirroring print_via_app.py's UI class. Coordinates are
    physical pixels; (ox, oy) is the Liene window's top-left. scale is informational (we work in
    physical px, so pt==px here) but kept so the flow code can stay symmetric with macOS."""

    def __init__(self, ox: int, oy: int, scale: float = 1.0):
        self.ox, self.oy, self.scale = ox, oy, scale
        self._pg, self._gw, self._clip, self._Image = _deps()

    def activate(self):
        win = find_liene_window(self._gw)
        if win is not None:
            try:
                win.activate()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.4)

    def abs(self, name):
        dx, dy = OFF[name]
        return self.ox + dx, self.oy + dy

    def click_pt(self, x, y, settle=0.6):
        self.activate()
        self._pg.click(int(x), int(y))
        time.sleep(settle)

    def click(self, name, settle=0.8):
        x, y = self.abs(name)
        self.click_pt(x, y, settle)

    def hotkey(self, *keys):
        self._pg.hotkey(*keys)

    def press(self, key):
        self._pg.press(key)

    def type_text(self, text):
        self._pg.typewrite(str(text), interval=0.02)

    def type_field(self, name, value):
        """Click a field, select-all, type the value, Enter (Windows = Ctrl, not Cmd)."""
        x, y = self.abs(name)
        self.click_pt(x, y, 0.4)
        self.hotkey("ctrl", "a")
        time.sleep(0.1)
        self.type_text(value)
        time.sleep(0.1)
        self.press("enter")
        time.sleep(0.5)

    def clip_set(self, text):
        self._clip.copy(str(text))

    def clip_get(self):
        return self._clip.paste()

    def paste(self):
        self.hotkey("ctrl", "v")

    def shot(self, path=None):
        self.activate()
        time.sleep(0.2)
        img = self._pg.screenshot()
        if path:
            img.save(path)
        return img.convert("RGB")

    def px2pt(self, px, py):
        return px / self.scale, py / self.scale

    def pt2px(self, x, y):
        return int(x * self.scale), int(y * self.scale)


def find_teal(img, ui, x0, y0, x1, y1, pick="bottom", min_px=40):
    """Teal accent button inside the points-rect (x0,y0)-(x1,y1). Same detector as macOS."""
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


# ---- CLI -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Windows Liene-app UI automation (PixCut S1).")
    ap.add_argument("command", choices=["probe", "print"],
                    help="probe = report geometry + screenshot for calibration; print = (TODO)")
    ap.add_argument("image", nargs="?", help="image to print (print command)")
    args = ap.parse_args()
    _require_win()
    if args.command == "probe":
        probe()
    else:
        sys.exit("The Windows print flow isn't calibrated yet. Run 'probe' first and send me "
                 "logs\\pixcut_probe.png so I can measure the OFFSETS.")


if __name__ == "__main__":
    main()
