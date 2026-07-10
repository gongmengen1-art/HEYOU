"""Cross-platform printing.

Two backends, chosen by `printing_cfg.backend`:
  * "system" (a.k.a. "lp" / "win") — the OS's normal printer: CUPS `lp`/`lpstat` on
    macOS/Linux, win32print + GDI on Windows. Works everywhere (install the PixCut as a
    system printer, then set `backend: system`).
  * "pixcut" — UI-automate the official Liene Photo app to get real die-cut printing. This
    is CROSS-PLATFORM now: macOS drives it via `pixcut-probe/print_via_app.sh` (osascript +
    CGEvent), Windows via `pixcut-probe/pixcut_win.py` (WebView2 CDP for the web home +
    SendInput for the Flutter editor). Linux has no pixcut path — use `backend: system`.

`print_output(path, printing_cfg)` / `backend_status(printing_cfg)` are the entry points the
app uses. Windows-only imports (pywin32) are done lazily inside the Windows functions so this
module still imports cleanly on macOS/Linux."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PRINT_COUNT_FILE = _PROJECT_ROOT / "data" / ".pixcut_print_count"

_IS_WINDOWS = sys.platform.startswith("win")
_IS_MAC = sys.platform == "darwin"


# ── System-printer backend: CUPS (lp) on POSIX ───────────────────────────────
def _list_lp() -> list[str]:
    try:
        out = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [line.split()[1] for line in out.stdout.splitlines() if line.startswith("printer ")]


def _print_lp(path: str, printer_name: str = "") -> tuple[bool, str]:
    cmd = ["lp"]
    if printer_name:
        cmd += ["-d", printer_name]
    cmd.append(str(path))
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return False, "`lp` command not found"
    except subprocess.TimeoutExpired:
        return False, "`lp` timed out"
    if out.returncode != 0:
        return False, out.stderr.strip() or "lp failed"
    return True, out.stdout.strip()


def _default_printer_lp() -> str:
    try:
        out = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    for line in out.stdout.splitlines():
        if "default destination:" in line:
            return line.split(":", 1)[1].strip()
    return ""


def _status_lp(printer_name: str = "") -> dict:
    target = printer_name or _default_printer_lp()
    if not target:
        return {"connected": False, "ok": False, "state": "无打印机", "name": ""}
    try:
        out = subprocess.run(["lpstat", "-p", target], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"connected": False, "ok": False, "state": "lpstat 不可用", "name": target}
    if out.returncode != 0 or not out.stdout.strip():
        return {"connected": False, "ok": False, "state": "未连接", "name": target}
    low = out.stdout.lower()
    if "disabled" in low or "stopped" in low:
        return {"connected": True, "ok": False, "state": "已停用", "name": target}
    if "printing" in low or "processing" in low:
        return {"connected": True, "ok": True, "state": "打印中", "name": target}
    return {"connected": True, "ok": True, "state": "就绪", "name": target}


# ── System-printer backend: win32print + GDI on Windows ──────────────────────
def _list_win() -> list[str]:
    try:
        import win32print
    except ImportError:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [p[2] for p in win32print.EnumPrinters(flags)]


def _print_win(path: str, printer_name: str = "") -> tuple[bool, str]:
    """Print an image on Windows by rendering it onto the printer's GDI device context,
    scaled to fit the printable page area (aspect-preserving, centered)."""
    try:
        import win32con
        import win32print
        import win32ui
        from PIL import Image, ImageWin
    except ImportError as e:
        return False, f"Windows 打印需要 pywin32（uv add pywin32 或 pip install pywin32）: {e}"
    target = printer_name or win32print.GetDefaultPrinter()
    if not target:
        return False, "没有可用的系统打印机（在 Windows 设置里把 PixCut 装为打印机）"
    try:
        img = Image.open(path).convert("RGB")
    except Exception as e:  # noqa: BLE001
        return False, f"无法打开图片: {e}"
    hdc = None
    try:
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(target)
        page_w = hdc.GetDeviceCaps(win32con.HORZRES)   # printable area, device pixels
        page_h = hdc.GetDeviceCaps(win32con.VERTRES)
        iw, ih = img.size
        scale = min(page_w / iw, page_h / ih)
        dw, dh = int(iw * scale), int(ih * scale)
        x, y = (page_w - dw) // 2, (page_h - dh) // 2
        hdc.StartDoc(str(path))
        hdc.StartPage()
        ImageWin.Dib(img).draw(hdc.GetHandleOutput(), (x, y, x + dw, y + dh))
        hdc.EndPage()
        hdc.EndDoc()
        return True, f"printed to {target} ({dw}x{dh}px)"
    except Exception as e:  # noqa: BLE001
        return False, f"Windows 打印失败: {e}"
    finally:
        if hdc is not None:
            try:
                hdc.DeleteDC()
            except Exception:  # noqa: BLE001
                pass


def _status_win(printer_name: str = "") -> dict:
    try:
        import win32print
    except ImportError:
        return {"connected": False, "ok": False, "state": "pywin32 未安装", "name": printer_name}
    target = printer_name or win32print.GetDefaultPrinter()
    if not target:
        return {"connected": False, "ok": False, "state": "无打印机", "name": ""}
    try:
        h = win32print.OpenPrinter(target)
        try:
            info = win32print.GetPrinter(h, 2)
        finally:
            win32print.ClosePrinter(h)
    except Exception:  # noqa: BLE001
        return {"connected": False, "ok": False, "state": "未连接", "name": target}
    status = info.get("Status", 0)
    if status == 0:
        return {"connected": True, "ok": True, "state": "就绪", "name": target}
    offline = getattr(win32print, "PRINTER_STATUS_OFFLINE", 0x80)
    printing = getattr(win32print, "PRINTER_STATUS_PRINTING", 0x400)
    if status & offline:
        return {"connected": False, "ok": False, "state": "离线", "name": target}
    if status & printing:
        return {"connected": True, "ok": True, "state": "打印中", "name": target}
    return {"connected": True, "ok": False, "state": f"状态码 {status}", "name": target}


# ── System-printer backend: cross-platform facade ────────────────────────────
def list_printers() -> list[str]:
    return _list_win() if _IS_WINDOWS else _list_lp()


def print_image(path: str, printer_name: str = "") -> tuple[bool, str]:
    """Print an image on the OS's system printer (Windows GDI or CUPS `lp`)."""
    return _print_win(str(path), printer_name) if _IS_WINDOWS else _print_lp(str(path), printer_name)


def printer_status(printer_name: str = "") -> dict:
    """Connection/health of the configured system printer (cross-platform)."""
    return _status_win(printer_name) if _IS_WINDOWS else _status_lp(printer_name)


# ── PixCut S1 (Liene-app UI automation) backend — macOS + Windows ────────────
def _liene_running() -> bool:
    """Is the Liene Photo app running? macOS: the 'Liene Photo' process; Windows:
    liene_photo_pc.exe."""
    if _IS_WINDOWS:
        try:
            out = subprocess.run(["tasklist", "/fi", "imagename eq liene_photo_pc.exe"],
                                 capture_output=True, text=True, timeout=8)
            return "liene_photo_pc.exe" in out.stdout.lower()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    try:
        r = subprocess.run(["pgrep", "-f", "Contents/MacOS/Liene Photo"],
                           capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _bump_print_count() -> int:
    """Increment and return the persistent pixcut print counter (used to decide restarts)."""
    try:
        n = int(_PRINT_COUNT_FILE.read_text().strip())
    except (OSError, ValueError):
        n = 0
    n += 1
    try:
        _PRINT_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PRINT_COUNT_FILE.write_text(str(n))
    except OSError:
        pass
    return n


def restart_liene_app(wait_sec: float = 30.0) -> bool:
    """Quit and relaunch Liene Photo so it returns to a clean home page with NO accumulated
    画板 tabs. Deterministic (pkill + open), no UI clicks. Returns True if it came back up."""
    subprocess.run(["pkill", "-f", "Contents/MacOS/Liene Photo"], capture_output=True)
    for _ in range(20):                       # wait for it to actually quit
        if not _liene_running():
            break
        time.sleep(0.5)
    subprocess.run(["open", "-a", "Liene Photo"], capture_output=True)
    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if _liene_running():
            time.sleep(6)                     # let the window + sign-in state finish loading
            return _liene_running()
        time.sleep(0.5)
    return False


def print_via_pixcut_win(path: str, pcfg) -> tuple[bool, str]:
    """Print on the PixCut S1 on WINDOWS by driving the Liene Photo app via pixcut_win.py
    (WebView2 CDP + SendInput). The script restarts the app itself for a clean start each run
    and returns to home afterwards, so no restart-counter bookkeeping is needed here. Drives
    the GUI (takes over the screen) and can take 2-3 min. `pcfg` is a PixcutCfg."""
    script = _PROJECT_ROOT / "pixcut-probe" / "pixcut_win.py"
    if not script.exists():
        return False, f"pixcut_win.py 未找到: {script}"
    sub = "dryrun" if getattr(pcfg, "dry_run", False) else "print"
    cmd = [sys.executable, str(script), sub, str(path)]
    if pcfg.margin_in:
        cmd += ["--margin", str(pcfg.margin_in)]
    # generous timeout: app restart (~30s) + upload/fit (~30s) + 切割预览 poll (~40s) +
    # print + job polling. wait_done inside the script caps at 300s.
    timeout = max(pcfg.timeout_sec, 480.0)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return False, f"无法执行 python 解释器 {sys.executable}"
    except subprocess.TimeoutExpired:
        return False, f"PixCut(Windows) 打印超时（{timeout:.0f}s）"
    lines = [l for l in (out.stdout or "").splitlines() if l.strip()]
    detail = lines[-1].strip() if lines else (out.stderr or "").strip()[-200:]
    # pixcut_win.py prints "DRY-RUN COMPLETED" / "PRINT COMPLETED" on success (rc 0).
    ok = out.returncode == 0 and ("COMPLETED" in (out.stdout or ""))
    if not ok:
        return False, detail or "pixcut_win.py 失败（见 logs\\cal_*.png）"
    return True, detail


def print_via_pixcut(path: str, pcfg) -> tuple[bool, str]:
    """Print on the PixCut S1 by UI-automating the Liene Photo app. Cross-platform: Windows
    dispatches to pixcut_win.py, macOS to print_via_app.sh. Drives the GUI (takes over the
    screen) and can take 1-3 min. `pcfg` is a PixcutCfg."""
    if _IS_WINDOWS:
        if not _liene_running():
            return False, "Liene Photo 未运行，请先打开并登录 App（极印 Photo）"
        return print_via_pixcut_win(path, pcfg)
    if not _IS_MAC:
        return False, "pixcut 后端仅支持 macOS 和 Windows；Linux 请用 backend: system"
    script = Path(pcfg.script)
    if not script.is_absolute():
        script = _PROJECT_ROOT / script
    if not script.exists():
        return False, f"print_via_app 脚本未找到: {script}"
    if not _liene_running():
        return False, "Liene Photo 未运行，请先打开并登录 App"
    cmd = [str(script)]
    if getattr(pcfg, "dry_run", False):
        cmd.append("--dry-run")
    if pcfg.cutout:
        cmd.append("--cutout")
    if pcfg.fresh:
        cmd.append("--fresh")
    if pcfg.margin_in:
        cmd += ["--margin", str(pcfg.margin_in)]
    cmd.append(str(path))
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=pcfg.timeout_sec)
    except FileNotFoundError:
        return False, f"无法执行 {script}（不可执行？）"
    except subprocess.TimeoutExpired:
        return False, f"PixCut 打印超时（{pcfg.timeout_sec:.0f}s）"
    # print_via_app logs to stderr; surface its last line as the detail
    lines = [l for l in (out.stderr or out.stdout).splitlines() if l.strip()]
    detail = lines[-1].strip() if lines else ""
    if out.returncode != 0:
        return False, detail or "print_via_app 失败"
    # Debug dry-run: nothing was printed — don't count it or trigger a restart.
    if getattr(pcfg, "dry_run", False):
        return True, detail or "DRY-RUN OK (no print)"
    # Success: bump the counter and, every N prints, restart the app to clear 画板 tabs
    # (in-canvas delete / tab-close via UI clicks is structurally unreliable in this app).
    n = _bump_print_count()
    every = getattr(pcfg, "restart_every", 0)
    if every and n % every == 0:
        ok = restart_liene_app()
        detail = f"{detail} | restarted Liene app to clear tabs (#{n}, {'ok' if ok else 'FAILED'})"
    return True, detail


# ── Dispatchers ──────────────────────────────────────────────────────────────
def print_output(path: str, printing_cfg) -> tuple[bool, str]:
    """Dispatch a print to the configured backend. `printing_cfg` is a PrintingCfg.
    backend "pixcut" → mac UI-automation; anything else ("system"/"lp"/"win") → system printer."""
    if getattr(printing_cfg, "backend", "system") == "pixcut":
        return print_via_pixcut(str(path), printing_cfg.pixcut)
    return print_image(str(path), printing_cfg.printer_name)


def backend_status(printing_cfg) -> dict:
    """Connection/health for the configured backend (PixCut = is the Liene app running)."""
    if getattr(printing_cfg, "backend", "system") == "pixcut":
        if not (_IS_MAC or _IS_WINDOWS):
            return {"connected": False, "ok": False, "state": "pixcut 仅 mac/Windows",
                    "name": "PixCut S1"}
        if _liene_running():
            return {"connected": True, "ok": True, "state": "就绪 (PixCut)", "name": "PixCut S1"}
        return {"connected": False, "ok": False, "state": "Liene App 未运行", "name": "PixCut S1"}
    return printer_status(printing_cfg.printer_name)
