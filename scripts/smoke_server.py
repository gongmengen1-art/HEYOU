"""In-process check of the console web app (no real port, no camera, no RunningHub generation)."""
import os
import sys
from pathlib import Path

os.environ["HEYOU_DISABLE_RECOGNITION"] = "1"  # don't open the camera during the smoke test
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from heyou.config import load_config
from heyou.server.app import app

cfg = load_config()
client = TestClient(app)

r = client.get("/")
print("GET / ->", r.status_code, f"(html {len(r.text)} chars)")
assert r.status_code == 200 and "HEYOU" in r.text

r = client.get("/api/status")
print("GET /api/status ->", r.status_code, r.json())
js = r.json()
assert r.status_code == 200 and "engine" in js and "printer" in js and "recognition" in js

sample = cfg.enrolled_dir / "_smoke_sample.jpg"
assert sample.exists(), f"missing sample image {sample} (run smoke_test.py first)"
with open(sample, "rb") as f:
    r = client.post("/api/enroll", data={"name": "SmokeTest"},
                    files={"file": ("s.jpg", f, "image/jpeg")})
print("POST /api/enroll ->", r.status_code, r.json())
assert r.status_code == 200
pid = r.json()["id"]

r = client.get("/api/people?page=1")
body = r.json()
print("GET /api/people ->", r.status_code, "page", body["page"], "/", body["pages"], "total", body["total"])
assert r.status_code == 200 and "items" in body and any(p["id"] == pid for p in body["items"])
me = next(p for p in body["items"] if p["id"] == pid)
assert me["generating"] is False and me["generated_today"] is False and me["last_output"] is None

r = client.get(f"/api/history/{pid}")
print(f"GET /api/history/{pid} ->", r.status_code, r.json())
assert r.status_code == 200 and isinstance(r.json(), list)

# manual print with nothing generated yet -> 400 (does NOT touch the printer)
r = client.post(f"/api/print/{pid}")
print(f"POST /api/print/{pid} ->", r.status_code, r.json())
assert r.status_code == 400

r = client.delete(f"/api/people/{pid}")
print(f"DELETE /api/people/{pid} ->", r.status_code, r.json())
assert r.status_code == 200

print("\nSERVER CHECKS PASSED ✅  (no RunningHub generation triggered)")
