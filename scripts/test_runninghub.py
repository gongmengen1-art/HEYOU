"""Single real RunningHub generation, downloading ALL outputs so we can see which
SaveImage node is the keeper. Consumes RH credits.

Usage:
    uv run python scripts/test_runninghub.py [image_path]
    (default: the first enrolled person's portrait)
"""
import logging
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from heyou import db
from heyou.config import load_config
from heyou.generation.runninghub import RunningHubBackend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

cfg = load_config()
cfg.ensure_dirs()

if len(sys.argv) > 1:
    img = sys.argv[1]
else:
    people = db.list_people(cfg.db_path)
    if not people:
        print("No enrolled people. Pass an image path: test_runninghub.py <path>")
        raise SystemExit(1)
    img = people[0]["photo_path"]

print(f"portrait: {img}")
backend = RunningHubBackend(cfg)
seed = random.randint(1, 2_000_000_000)
urls = backend.run_task(img, seed)
print(f"\n{len(urls)} output(s):")
with httpx.Client(timeout=60.0) as client:
    for i, u in enumerate(urls):
        resp = client.get(u)
        out = cfg.output_dir / f"rh_test_{seed}_{i}.png"
        out.write_bytes(resp.content)
        print(f"  [{i}] {len(resp.content):>8} bytes -> {out}   ({u})")

print("\nDone. Open the rh_test_*.png files and tell me which index is the good one.")
