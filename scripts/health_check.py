"""Structural health-check of a ComfyUI/RunningHub workflow JSON.

Flags things that commonly break community workflows on import:
  - muted (mode=2) / bypassed (mode=4) nodes
  - dangling input links / links whose endpoints reference missing nodes
  - "Use Everywhere" / Reroute nodes (implicit wiring that often breaks)
  - the full list of referenced model files (missing ones => fatal on another account)

Usage:  uv run python scripts/health_check.py [path]
"""
import json
import sys
from collections import Counter
from pathlib import Path

path = sys.argv[1] if len(sys.argv) > 1 else "workflows/cute_you_2.json"
d = json.loads(Path(path).read_text(encoding="utf-8"))
nodes = {n["id"]: n for n in d["nodes"]}
links = d.get("links", [])
link_ids = {l[0] for l in links}

MODE = {0: "active", 2: "MUTED", 4: "BYPASSED"}
muted = [(n["id"], n.get("type"), MODE.get(n.get("mode"), n.get("mode")))
         for n in d["nodes"] if n.get("mode") not in (0, None)]

dangling = []
for n in d["nodes"]:
    for inp in (n.get("inputs") or []):
        lk = inp.get("link")
        if lk is not None and lk not in link_ids:
            dangling.append((n["id"], n.get("type"), inp.get("name"), lk))

broken_endpoints = [l for l in links if l[1] not in nodes or l[3] not in nodes]

EXTS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".onnx")
models = []
for n in d["nodes"]:
    for w in (n.get("widgets_values") or []):
        if isinstance(w, str) and w.lower().endswith(EXTS):
            models.append((n["id"], n.get("type"), w))

types = Counter(n.get("type") for n in d["nodes"])
implicit = [(n["id"], n.get("type")) for n in d["nodes"]
            if any(k in (n.get("type") or "").lower() for k in ("everywhere", "reroute", "anything"))]

print(f"== {path}: {len(d['nodes'])} nodes, {len(links)} links ==\n")
print(f"MUTED / BYPASSED nodes ({len(muted)}):")
for m in muted:
    print("   ", m)
print(f"\nDANGLING input links ({len(dangling)}):")
for x in dangling:
    print("   ", x)
print(f"\nBROKEN link endpoints ({len(broken_endpoints)}):")
for x in broken_endpoints:
    print("   ", x)
print(f"\nImplicit-wiring nodes (Use-Everywhere / Reroute) ({len(implicit)}):")
for x in implicit:
    print("   ", x)
print(f"\nReferenced MODEL files ({len(models)}):")
for x in models:
    print("   ", x)
print("\nNode type counts:")
for t, c in types.most_common():
    print(f"   {c:>2}  {t}")
