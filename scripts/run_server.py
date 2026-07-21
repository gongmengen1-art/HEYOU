"""Start the bar-owner enrollment web app.

Host/port come from config.yaml (server.host / server.port) but can be overridden with the
HEYOU_HOST / HEYOU_PORT environment variables — the Windows one-click launcher sets
HEYOU_HOST=0.0.0.0 to open the console to the LAN. Binding 0.0.0.0 makes the console
reachable from any device on the same network, and there is no login yet, so only do it on
a trusted network.
"""
import logging
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from heyou.config import load_config


def _lan_ips() -> list[str]:
    """Best-effort list of this machine's LAN IPv4 addresses (for the startup banner)."""
    ips: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))          # no packet is sent; just picks the outbound interface
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass
    return sorted(ips)


if __name__ == "__main__":
    from heyou.server.app import app

    cfg = load_config()
    host = os.environ.get("HEYOU_HOST", cfg.server.host)
    port = int(os.environ.get("HEYOU_PORT", cfg.server.port))
    print(f"Enrollment app → http://{host}:{port}")
    if host in ("0.0.0.0", "::"):
        for ip in _lan_ips():
            print(f"    LAN access → http://{ip}:{port}")
    # log_config=None: importing heyou.server.app already attached our rotating file +
    # stderr handlers to the root logger; this lets uvicorn's own loggers propagate into
    # them (so its output is captured + rotated) instead of being overridden.
    try:
        uvicorn.run(app, host=host, port=port, log_config=None)
    except Exception:
        # e.g. port already in use (WinError 10048) — land it in data/logs/heyou.log too,
        # not only on the console, so the persistent log explains the crash.
        logging.getLogger("heyou").exception("server failed to start / crashed")
        raise
