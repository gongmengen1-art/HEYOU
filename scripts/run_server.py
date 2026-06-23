"""Start the bar-owner enrollment web app."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from heyou.config import load_config
from heyou.server.app import app

if __name__ == "__main__":
    cfg = load_config()
    print(f"Enrollment app → http://{cfg.server.host}:{cfg.server.port}")
    # log_config=None: importing heyou.server.app already attached our rotating file +
    # stderr handlers to the root logger; this lets uvicorn's own loggers propagate into
    # them (so its output is captured + rotated) instead of being overridden.
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_config=None)
