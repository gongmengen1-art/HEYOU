#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
print_via_app.py — drive the official Liene Photo.app (极印 / Creativerse) UI to print
an image on the PixCut S1, optionally with AI die-cut (抠图). This bypasses the
unfinished direct-USB data-framing path: the app handles transport+framing itself
(over Bluetooth) and prints reliably.

Validated end-to-end on 2026-06-22 (real prints, jobs 33 & 34). See the
pixcut-s1-protocol memory for the full reverse-engineering notes.

USAGE
  ./print_via_app.sh [options] <image>
    --cutout        apply AI抠图 (die-cut around the subject) before printing
    --dry-run       do everything up to the 切割 (Cut/print) button, but DO NOT click it
                    (places + sizes the image and opens the cut preview, no ribbon used)
    --fresh         navigate Home -> 画板 -> 创建设计 -> blank 4x7 canvas first
                    (use after an app restart, or when not already in the editor)
    --keep          do not delete the placed image after printing
    --no-wait       don't poll the app log for job completion
    --margin INCH   shrink the fitted image by this margin on each side (default 0.0)
    --log-retention-days N  prune Liene's own logs older than N days (default 7; 0=off)
    --no-log-clean  skip the Liene log cleanup for this run

NOTES / ASSUMPTIONS
  * The app must be running and signed in, with the editor showing a 4x7 canvas
    (unless --fresh). Window must be the normal size (~1280x760 content).
  * Accessibility + Screen Recording must be granted to the controlling terminal.
  * Coordinates are anchored to the live window origin (detected each run); the
    per-control OFFSETS below assume the standard window size. If the app window is
    resized, re-measure the offsets.
  * ALWAYS validate a new image first with --dry-run (no ribbon), then run for real.
"""
import sys, os, re, time, subprocess, argparse, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
CLICK = os.path.join(HERE, "click")            # CGEvent clicker (./click x y)
AXENABLE = os.path.join(HERE, "axenable")      # AX-enable + tree dump (./axenable pid)
APP_NAME = "Liene Photo"
LIENE_LOG_DIR = os.path.expanduser(
    "~/Library/Containers/com.hannto.photomacos/Data/Library/Logs/com.hannto.photomacos")
LIENE_ANALYTICS_DIR = os.path.expanduser(
    "~/Library/Containers/com.hannto.photomacos/Data/Library/Application Support/"
    "com.hannto.photomacos/Analytics")
LOG_GLOB = os.path.join(LIENE_LOG_DIR, "liene_photo_pc_*.log")

# Canvas paper size (inches). The blank "用于4*7相纸" canvas.
CANVAS_W_IN, CANVAS_H_IN = 4.0, 7.0

# Per-control offsets in screen POINTS, relative to the window origin (ox, oy).
# Measured on the standard 1280x760 window. abs = (ox+dx, oy+dy).
OFF = {
    "queue_x":      (1248, 24),   # ✕ that closes the 任务队列 (print queue) panel
    "home_btn":     (223, 24),    # 🏠首页 button (top bar) -> back to Creativerse home
    "huaban_tab":   (1103, 55),   # 画板 tab on Home (only --fresh)
    "blank_plus":   (517, 305),   # 创建设计 modal: the "+" 用于4*7相纸 box (only --fresh)
    "upload_tool":  (34, 261),    # left toolbar: 上传
    "upload_btn":   (234, 97),    # teal 上传图片 button (top of the upload panel)
    "apply_btn":    (640, 645),   # teal 应用 in the 效果图 modal (place original)
    "ai_cutout":    (1157, 717),  # right panel 工具 > AI抠图 (on a selected object)
    "next_btn":     (643, 656),   # teal 下一步 at the AI抠图 modal bottom (fallback; do_cutout polls)
    "fld_w":        (1092, 508),  # 高级 W field
    "fld_h":        (1185, 508),  # 高级 H field
    "fld_x":        (1092, 548),  # 高级 X field
    "fld_y":        (1185, 548),  # 高级 Y field
    "make_btn":     (1235, 52),   # pale-teal 制作 (top-right, 2nd row) -> opens 切割预览
    "cut_btn":      (840, 592),   # teal 切割 (bottom-right of 切割预览) -> PRINTS
    "cut_preview_x":(759, 120),   # ✕ of the 切割预览 modal (used by --dry-run to close it, NOT print)
}

def log(*a):
    print("[print_via_app]", *a, file=sys.stderr, flush=True)

def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

def osa(script):
    return subprocess.run(["osascript", "-e", script], capture_output=True, text=True).stdout.strip()

def activate():
    osa(f'tell application "{APP_NAME}" to activate')
    time.sleep(0.5)

def app_pid():
    r = sh('pgrep -f "Contents/MacOS/Liene Photo"')
    pids = [p for p in r.stdout.split() if p]
    if not pids:
        sys.exit(f"ERROR: {APP_NAME} is not running. Open it first.")
    return int(pids[0])

# ---- geometry -------------------------------------------------------------
def get_window(pid):
    """Return (ox, oy, w, h) of the app window in screen points. Retries axenable."""
    for _ in range(4):
        activate()
        out = sh(f'"{AXENABLE}" {pid}').stdout
        m = re.search(r"AXWindow '[^']*' @(-?\d+),(-?\d+) \[(\d+)x(\d+)\]", out)
        if m:
            return tuple(int(x) for x in m.groups())
        time.sleep(0.4)
    # Fallback to System Events
    pos = osa(f'tell application "System Events" to tell process "{APP_NAME}" to get position of window 1')
    sz  = osa(f'tell application "System Events" to tell process "{APP_NAME}" to get size of window 1')
    try:
        ox, oy = [int(v) for v in pos.split(",")]
        w, h   = [int(v) for v in sz.split(",")]
        return ox, oy, w, h
    except Exception:
        sys.exit("ERROR: could not read window geometry (try --fresh / re-activate the app).")

def detect_scale():
    """screenshot pixels per screen point (Retina = 2)."""
    sh("screencapture -x /tmp/_pv_full.png")
    from PIL import Image
    pw = Image.open("/tmp/_pv_full.png").width
    desk = osa('tell application "Finder" to get bounds of window of desktop')  # "0, 0, W, H"
    try:
        dw = int(desk.split(",")[2])
    except Exception:
        dw = pw // 2
    return round(pw / dw) or 2

# ---- input ----------------------------------------------------------------
class UI:
    def __init__(self, ox, oy, scale):
        self.ox, self.oy, self.scale = ox, oy, scale
    def abs(self, name):
        dx, dy = OFF[name]
        return self.ox + dx, self.oy + dy
    def click_pt(self, x, y, settle=0.6):
        activate()
        subprocess.run([CLICK, str(int(x)), str(int(y))])
        time.sleep(settle)
    def click(self, name, settle=0.8):
        x, y = self.abs(name)
        self.click_pt(x, y, settle)
    def key(self, applescript_key):
        osa(f'tell application "System Events" to {applescript_key}')
    def type_field(self, name, value):
        x, y = self.abs(name)
        self.click_pt(x, y, 0.4)
        osa('tell application "System Events" to tell process "%s"\n'
            ' set frontmost to true\n delay 0.15\n'
            ' keystroke "a" using {command down}\n delay 0.1\n'
            ' keystroke "%s"\n delay 0.1\n keystroke return\n end tell' % (APP_NAME, value))
        time.sleep(0.6)
    def shot(self, path="/tmp/_pv.png"):
        activate(); time.sleep(0.2)
        sh(f"screencapture -x {path}")
        from PIL import Image
        return Image.open(path).convert("RGB")
    # px (full-screen screenshot) <-> screen points
    def px2pt(self, px, py):
        return px / self.scale, py / self.scale
    def pt2px(self, x, y):
        return int(x * self.scale), int(y * self.scale)

# ---- vision helpers -------------------------------------------------------
def find_teal(img, ui, x0, y0, x1, y1, pick="bottom", min_px=40):
    """Find the teal accent button inside the points-rect (x0,y0)-(x1,y1).
    Returns (sx,sy) screen points of the chosen cluster centroid, or None.
    Requires at least `min_px` matching samples so stray anti-aliased edges (a handful
    of teal-ish pixels) don't register as a button — a real button yields hundreds."""
    px = img.load()
    X0, Y0 = ui.pt2px(x0, y0); X1, Y1 = ui.pt2px(x1, y1)
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
    cx = sum(p[0] for p in pts) / len(pts); cy = sum(p[1] for p in pts) / len(pts)
    return ui.px2pt(cx, cy)

def artboard_rect_px(img, ui):
    """Bounding box (in PIXELS) of the white 4x7 canvas, searched in the canvas
    viewport between the side panels. Run when the canvas is blank."""
    px = img.load()
    x0, y0 = ui.pt2px(ui.ox + 225, ui.oy + 60)
    x1, y1 = ui.pt2px(ui.ox + 1010, ui.oy + 750)
    xs, ys = [], []
    for y in range(int(y0), int(y1), 2):
        for x in range(int(x0), int(x1), 2):
            r, g, b = px[x, y]
            if r > 250 and g > 250 and b > 250:
                xs.append(x); ys.append(y)
    if len(xs) < 50:
        return None
    return min(xs), min(ys), max(xs), max(ys)

def object_bbox_px(img, ui, region_px, cyan_only=False):
    """Bounding box (PIXELS) of placed object inside region_px=(x0,y0,x1,y1).
    cyan_only: use the selection handles (precise, content-independent)."""
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
                if min(r, g, b) < 233:    # non-white (object)
                    xs.append(x); ys.append(y)
    if len(xs) < 20:
        return None
    return min(xs), min(ys), max(xs), max(ys)

# ---- high-level steps -----------------------------------------------------
def clear_canvas(ui):
    """Delete any object currently on the canvas (so the next image doesn't overlap)."""
    img = ui.shot()
    region = (*ui.pt2px(ui.ox + 255, ui.oy + 95), *ui.pt2px(ui.ox + 1005, ui.oy + 710))
    bb = object_bbox_px(img, ui, region, cyan_only=False)
    if not bb:
        log("canvas already clear")
        return
    cx_pt, cy_pt = ui.px2pt((bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2)
    top_pt = ui.px2pt(0, bb[1])[1]
    ui.click_pt(cx_pt, cy_pt, 0.7)            # select
    # trash icon floats ~49 pt above the object's top edge, centered on the object
    ui.click_pt(cx_pt, top_pt - 49, 0.9)      # 🗑
    log("deleted existing object")
    time.sleep(0.5)

def go_home(ui):
    """Return to the Creativerse home page from anywhere (editor + open panels). Clicking 首页
    while an overlay is up (e.g. the 任务队列 panel) only dismisses the overlay, so click twice
    — the 2nd click navigates. Idempotent once on home. This is the 'clean start' for route B."""
    for _ in range(2):
        ui.click("home_btn", settle=1.3)


def go_fresh(ui):
    """Home -> 画板 -> 创建设计 -> blank 4x7 canvas. Goes home first so it works regardless of
    what the previous print left behind (editor + queue panel + placed image)."""
    log("navigating Home -> blank 4x7 canvas")
    go_home(ui)
    ui.click("huaban_tab", settle=1.5)
    ui.click("blank_plus", settle=3.0)

def open_upload_panel(ui):
    """Ensure the left 上传 panel is open (idempotent — clicking the tool toggles it).
    Detect via the teal 上传图片 button at the panel top. Re-checks AFTER each click (not
    just before) so the final toggle is confirmed — otherwise an even click count can leave
    the panel closed while the pre-click checks never saw it open."""
    rect = (ui.ox + 10, ui.oy + 80, ui.ox + 440, ui.oy + 125)
    for _ in range(4):
        if find_teal(ui.shot(), ui, *rect, pick="any"):
            return True
        ui.click("upload_tool", settle=1.3)
        if find_teal(ui.shot(), ui, *rect, pick="any"):
            return True
    log("WARN: upload panel may not be open")
    return False

def upload_image(ui, image_path):
    """Assumes the upload panel is open. Pick the file via the native open panel and
    place the original onto the canvas (clicks 应用). Object ends up selected."""
    img = ui.shot()
    p = find_teal(img, ui, ui.ox + 10, ui.oy + 80, ui.ox + 440, ui.oy + 125, pick="any")
    if p: ui.click_pt(p[0], p[1], 1.5)        # teal 上传图片 -> native open panel
    else: ui.click("upload_btn", settle=1.5)
    # wait for the sheet
    for _ in range(12):
        if osa(f'tell application "System Events" to tell process "{APP_NAME}" to count sheets of window 1') == "1":
            break
        time.sleep(0.5)
    # paste the path via Go-to-folder, then click Open
    subprocess.run("pbcopy", input=image_path, text=True, shell=True)
    osa('tell application "System Events" to tell process "%s"\n set frontmost to true\n'
        ' delay 0.3\n keystroke "g" using {command down, shift down}\n delay 0.8\n'
        ' keystroke "a" using {command down}\n delay 0.15\n key code 51\n delay 0.15\n'
        ' keystroke "v" using {command down}\n delay 0.4\n keystroke return\n delay 1.2\n'
        ' try\n  click (first button of sheet 1 of window 1 whose name is "Open")\n'
        ' on error\n  keystroke return\n end try\n end tell' % APP_NAME)
    time.sleep(2.5)
    # 效果图 modal -> 应用 (place original). Detect the teal button near modal bottom.
    img = ui.shot()
    p = find_teal(img, ui, ui.ox + 300, ui.oy + 560, ui.ox + 980, ui.oy + 700, pick="bottom")
    if p: ui.click_pt(p[0], p[1], 2.0)
    else: ui.click("apply_btn", settle=2.0)
    log("image placed (original)")

def do_cutout(ui):
    """On the selected object: 工具 > AI抠图 -> wait for the result -> 下一步 (replaces with
    die-cut). The cloud cutout can take 10-25s, so POLL for the teal 下一步 button (modal
    bottom, ~window-pt (643,656)) rather than a fixed sleep — a fixed 9s clicked white space
    above the not-yet-rendered button, leaving the modal open and the object unplaced (which
    then made the aspect read fail)."""
    log("applying AI抠图 (die-cut)...")
    ui.click("ai_cutout", settle=2.0)
    p = None
    for _ in range(20):                       # poll up to ~30s for the result + 下一步 button
        p = find_teal(ui.shot(), ui, ui.ox + 300, ui.oy + 560, ui.ox + 980, ui.oy + 720, pick="bottom")
        if p:
            break
        time.sleep(1.5)
    if p:
        ui.click_pt(p[0], p[1], 2.5)
    else:
        log("WARN: 下一步 not found after cutout; using offset fallback")
        ui.click("next_btn", settle=2.5)
    log("cutout placed")

def read_field(ui, name):
    """Click a 高级 field, select-all + copy, and return the clipboard text (its value)."""
    x, y = ui.abs(name)
    ui.click_pt(x, y, 0.4)
    osa('tell application "System Events" to tell process "%s"\n set frontmost to true\n'
        ' delay 0.12\n keystroke "a" using {command down}\n delay 0.1\n'
        ' keystroke "c" using {command down}\n delay 0.1\n end tell' % APP_NAME)
    time.sleep(0.2)
    return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout.strip()


def object_aspect(ui):
    """Aspect (w/h) of the placed+selected object, read DIRECTLY from the app's own 高级 W/H
    fields (select-all + copy). This is the app's exact dimension for the object — for a
    die-cut it's the subject's cropped W/H — so it needs no canvas vision and is immune to the
    panel-shift / teal-UI confounds that defeated pixel measurement. (Verified: a plain place
    of an 800×1400 image read W=0.9 H=1.57 → 0.573 = the true 0.571.)"""
    try:
        w = float(read_field(ui, "fld_w"))
        h = float(read_field(ui, "fld_h"))
    except (ValueError, TypeError):
        return None
    return (w / h) if h > 0 else None

def fit_and_center(ui, aspect, margin=0.0):
    """Scale the placed object to fill the 4x7 canvas (no distortion) and center it,
    using only its aspect ratio. `aspect` = width/height of the image content."""
    if not aspect or aspect <= 0:
        log("WARN: unknown aspect; skipping fit (leaving default size)")
        return
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

def open_cut_preview(ui):
    ui.click("make_btn", settle=4.5)          # 制作 -> 切割预览 (has a load delay)
    # Verify the preview actually opened: it shows a teal 切割 button near the bottom-right.
    # (Don't trust the click silently — a missed 制作 used to leave us on a blank canvas.)
    for _ in range(3):
        img = ui.shot()
        if find_teal(img, ui, ui.ox + 620, ui.oy + 560, ui.ox + 1020, ui.oy + 660, pick="bottom"):
            return True
        time.sleep(1.5)
    log("WARN: 切割预览 did not open (制作 may have missed); check make_btn offset")
    return False

def do_print(ui):
    img = ui.shot()
    p = find_teal(img, ui, ui.ox + 620, ui.oy + 560, ui.ox + 1020, ui.oy + 660, pick="bottom")
    if p: ui.click_pt(p[0], p[1], 1.0)
    else: ui.click("cut_btn", settle=1.0)
    log("clicked 切割 — printing")

def prune_liene_logs(retention_days=7, keep_recent=3):
    """Delete Liene Photo's OWN log files (it writes a fresh, fat liene_photo_pc_*.log
    every session plus daily AnalyticsSDK logs, and never cleans them up). Removes files
    older than `retention_days`, but ALWAYS keeps the newest `keep_recent` per directory
    so the active session log (polled by wait_done) is never touched. retention_days <= 0
    disables. Returns (removed_count, freed_bytes)."""
    if retention_days <= 0:
        return 0, 0
    import glob
    cutoff = time.time() - retention_days * 86400
    removed = freed = 0
    patterns = [
        os.path.join(LIENE_LOG_DIR, "liene_photo_pc_*.log"),
        os.path.join(LIENE_ANALYTICS_DIR, "AnalyticsSDK*.log"),
    ]
    for pat in patterns:
        files = sorted(glob.glob(pat), key=os.path.getmtime, reverse=True)
        for f in files[keep_recent:]:          # protect the newest keep_recent per dir
            try:
                if os.path.getmtime(f) < cutoff:
                    sz = os.path.getsize(f)
                    os.remove(f)
                    removed += 1; freed += sz
            except OSError:
                pass
    if removed:
        log(f"pruned {removed} old Liene log file(s), freed {freed // 1024} KB")
    return removed, freed


def wait_done(timeout=300):
    import glob
    files = sorted(glob.glob(LOG_GLOB), key=os.path.getmtime)
    if not files:
        log("WARN: no app log found; cannot poll completion"); return None
    logf = files[-1]
    start = time.time()
    last = ""
    while time.time() - start < timeout:
        out = sh(f'grep -a "getJobInfo\\|get-job-info" "{logf}" | tail -1').stdout
        m = re.search(r'"job-state":(\d+).*?"job-sub-state":(\d+)', out)
        rib = re.search(r'"ribbon-cnt":(\d+)', out)
        if m:
            cur = f'state={m.group(1)}/{m.group(2)} ribbon={rib.group(1) if rib else "?"}'
            if cur != last:
                log("  " + cur); last = cur
            if m.group(1) == "9":
                log("DONE — job completed.")
                return True
        time.sleep(4)
    log("WARN: timed out waiting for completion")
    return False

# ---- main -----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--cutout", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--margin", type=float, default=0.0)
    ap.add_argument("--log-retention-days", type=int, default=7,
                    help="prune Liene's own logs older than this many days (0 = keep all)")
    ap.add_argument("--no-log-clean", action="store_true",
                    help="skip the Liene log cleanup for this run")
    args = ap.parse_args()

    image = os.path.abspath(args.image)
    if not os.path.exists(image):
        sys.exit(f"ERROR: image not found: {image}")
    for tool in (CLICK, AXENABLE):
        if not os.path.exists(tool):
            sys.exit(f"ERROR: missing helper {tool} (build it first; see memory).")

    if not args.no_log_clean:
        prune_liene_logs(args.log_retention_days)

    pid = app_pid()
    ox, oy, w, h = get_window(pid)
    scale = detect_scale()
    log(f"window @({ox},{oy}) {w}x{h}  scale={scale}  pid={pid}")
    if not (1180 <= w <= 1380 and 700 <= h <= 860):
        log(f"WARN: window size {w}x{h} differs from the standard ~1280x760; "
            "offsets may be off. Resize the app window or re-measure OFF[].")
    ui = UI(ox, oy, scale)

    # dismiss any stray centered modal (cut preview / settings) left from a prior run
    ui.key("key code 53"); time.sleep(0.3)
    ui.key("key code 53"); time.sleep(0.3)
    if args.fresh:
        go_fresh(ui)                      # brand-new canvas is empty — nothing to clear
    else:
        clear_canvas(ui)                  # remove any object left from a prior run

    open_upload_panel(ui)
    upload_image(ui, image)
    if args.cutout:
        do_cutout(ui)
        aspect = object_aspect(ui)        # read the cutout's W/H from the app's 高级 fields
        log(f"cutout aspect detected: {aspect}")
    else:
        from PIL import Image as _PILImage
        iw, ih = _PILImage.open(image).size
        aspect = iw / ih
    fit_and_center(ui, aspect, margin=args.margin)
    open_cut_preview(ui)

    if args.dry_run:
        # DEBUG: reached the final 切割预览 — do NOT click 切割 (no print, no ribbon). Close the
        # preview instead so the run leaves a clean state (go_home below) and can repeat.
        log("DRY RUN — reached 切割预览; NOT clicking 切割 (no print, no ribbon).")
        ui.click("cut_preview_x", settle=0.8)
    else:
        do_print(ui)
        if not args.no_wait:
            wait_done()
    if not args.keep:
        # Route B: return to a clean home page instead of trying to delete the just-printed
        # object in place (the trash icon has no room above a full-bleed image) or close the
        # 任务队列 panel by guessing its ✕. go_home also dismisses that panel; the next print's
        # --fresh then starts from a known-clean home.
        time.sleep(1.0)
        go_home(ui)
    log("DRY-RUN OK — full flow completed without printing." if args.dry_run else "finished.")

if __name__ == "__main__":
    main()
