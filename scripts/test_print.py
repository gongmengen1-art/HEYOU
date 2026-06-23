"""Manually print an image to validate the HP printer (no camera, no generation).

Usage:  uv run python scripts/test_print.py data/outputs/<file>.png
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heyou.config import load_config
from heyou.printing import list_printers, print_image

cfg = load_config()
print("available printers:", list_printers())
print("configured printer_name:", repr(cfg.printing.printer_name) or "(system default)")

if len(sys.argv) < 2:
    print("\nusage: test_print.py <image_path>")
    raise SystemExit(1)

ok, detail = print_image(sys.argv[1], cfg.printing.printer_name)
print("print:", "OK ✅" if ok else "FAILED ❌", "-", detail)
