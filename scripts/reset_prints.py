"""Clear today's print state so you can re-trigger generation while testing.

Usage:
    uv run python scripts/reset_prints.py          # reset everyone
    uv run python scripts/reset_prints.py 1        # reset only person id 1
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heyou import db
from heyou.config import load_config

cfg = load_config()
pid = int(sys.argv[1]) if len(sys.argv) > 1 else None
with db.connect(cfg.db_path) as conn:
    if pid is not None:
        conn.execute("UPDATE people SET last_print_date=NULL WHERE id=?", (pid,))
        print(f"reset print state for person {pid}")
    else:
        conn.execute("UPDATE people SET last_print_date=NULL")
        print("reset print state for ALL people")
