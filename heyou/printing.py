"""Printing backends: CUPS `lp` (system printer) or the PixCut S1 via Liene-app UI automation.

`print_output(path, printing_cfg)` is the single entry point the app uses; it dispatches on
`printing_cfg.backend` ("lp" | "pixcut"). The pixcut backend shells out to
`pixcut-probe/print_via_app.sh`, which drives the official Liene Photo app's GUI (it takes over
the mouse/screen and can take 1-2 min per print)."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PRINT_COUNT_FILE = _PROJECT_ROOT / "data" / ".pixcut_print_count"


def list_printers() -> list[str]:
    try:
        out = subprocess.run(["lpstat", "-p"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    names = []
    for line in out.stdout.splitlines():
        # e.g. "printer HP_OfficeJet is idle.  enabled since ..."
        if line.startswith("printer "):
            names.append(line.split()[1])
    return names


def print_image(path: str, printer_name: str = "") -> tuple[bool, str]:
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


def _default_printer() -> str:
    try:
        out = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    for line in out.stdout.splitlines():
        if "default destination:" in line:
            return line.split(":", 1)[1].strip()
    return ""


def printer_status(printer_name: str = "") -> dict:
    """Report whether a printer is connected and healthy (via CUPS `lpstat`)."""
    target = printer_name or _default_printer()
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


# ── PixCut S1 (Liene-app UI automation) backend ──────────────────────────────
def _liene_running() -> bool:
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


def print_via_pixcut(path: str, pcfg) -> tuple[bool, str]:
    """Print on the PixCut S1 by UI-automating the Liene Photo app via print_via_app.sh.
    Drives the GUI (takes over the screen) and can take 1-2 min. `pcfg` is a PixcutCfg."""
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


def print_output(path: str, printing_cfg) -> tuple[bool, str]:
    """Dispatch a print to the configured backend. `printing_cfg` is a PrintingCfg."""
    if getattr(printing_cfg, "backend", "lp") == "pixcut":
        return print_via_pixcut(str(path), printing_cfg.pixcut)
    return print_image(str(path), printing_cfg.printer_name)


def backend_status(printing_cfg) -> dict:
    """Connection/health for the configured backend (PixCut = is the Liene app running)."""
    if getattr(printing_cfg, "backend", "lp") == "pixcut":
        if _liene_running():
            return {"connected": True, "ok": True, "state": "就绪 (PixCut)", "name": "PixCut S1"}
        return {"connected": False, "ok": False, "state": "Liene App 未运行", "name": "PixCut S1"}
    return printer_status(printing_cfg.printer_name)
