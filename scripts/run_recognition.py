"""Start the camera recognition + generation loop."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heyou.config import load_config
from heyou.orchestrator import run

if __name__ == "__main__":
    run(load_config())
