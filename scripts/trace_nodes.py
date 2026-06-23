"""Trace input/output wiring of key nodes to find the real inject points.

Usage:  uv run python scripts/trace_nodes.py [path]
"""
import json
import sys
from pathlib import Path

path = sys.argv[1] if len(sys.argv) > 1 else "workflows/cute_you_2.json"
d = json.loads(Path(path).read_text(encoding="utf-8"))
nodes = {n["id"]: n for n in d["nodes"]}
links = {l[0]: l for l in d.get("links", [])}  # id -> [id, from, from_slot, to, to_slot, type]


def label(nid) -> str:
    n = nodes.get(nid, {})
    t = n.get("title") or ""
    return f"{nid}:{n.get('type')}" + (f"«{t}»" if t else "")


def trace(nid) -> None:
    n = nodes[nid]
    print(f"\n### {label(nid)}   widgets={n.get('widgets_values')}")
    for inp in n.get("inputs", []):
        lk = inp.get("link")
        src = label(links[lk][1]) if (lk is not None and lk in links) else "(widget/none)"
        print(f"    in  {inp['name']:<16} <- {src}")
    for out in n.get("outputs", []):
        tgts = [label(links[lk][3]) for lk in (out.get("links") or []) if lk in links]
        if tgts:
            print(f"    out {out['name']:<16} -> {tgts}")


# Auto-collect the node types we care about
WANT = ("loadimage", "easy seed", "ksampler", "text _o", "sdxlpromptstyler",
        "applyinstantid", "applypulid", "ipadapteradvanced", "cliptextencode")
ids = [n["id"] for n in d["nodes"] if any(w in (n.get("type", "").lower()) for w in WANT)]
for nid in ids:
    trace(nid)
