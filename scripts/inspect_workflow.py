"""Print a ComfyUI/RunningHub workflow's node structure to locate inject points.

Usage:  uv run python scripts/inspect_workflow.py [path]
"""
import json
import sys
from pathlib import Path

path = sys.argv[1] if len(sys.argv) > 1 else "workflows/cute_you_2.json"
data = json.loads(Path(path).read_text(encoding="utf-8"))

KEYWORDS = ["loadimage", "image", "pulid", "instantid", "ipadapter", "faceanalysis",
            "reactor", "ksampler", "sampler", "cliptextencode", "text", "seed", "noise"]


def is_interesting(*parts) -> bool:
    low = " ".join(str(p) for p in parts).lower()
    return any(k in low for k in KEYWORDS)


def show_api(nodes: dict) -> None:
    print(f"FORMAT: API (dict keyed by node id), {len(nodes)} nodes\n")
    cands = []
    for nid, node in nodes.items():
        ct = node.get("class_type", "?")
        title = (node.get("_meta") or {}).get("title", "")
        inputs = node.get("inputs", {})
        lits = {k: v for k, v in inputs.items() if not isinstance(v, list)}
        print(f"[{nid:>4}] {ct}  «{title}»")
        if lits:
            print(f"        literals: {lits}")
        if is_interesting(ct, title):
            cands.append((nid, ct, title, lits))
    print("\n=== CANDIDATE INJECT POINTS ===")
    for nid, ct, title, lits in cands:
        print(f"[{nid}] {ct} «{title}»  {lits}")


def show_ui(d: dict) -> None:
    nodes = d["nodes"]
    print(f"FORMAT: UI (nodes array), {len(nodes)} nodes\n")
    cands = []
    for node in nodes:
        nid = node.get("id")
        ct = node.get("type")
        title = node.get("title") or ""
        wv = node.get("widgets_values", [])
        print(f"[{nid:>4}] {ct}  «{title}»  widgets={wv}")
        if is_interesting(ct, title):
            cands.append((nid, ct, title, wv))
    print("\n=== CANDIDATE INJECT POINTS ===")
    for nid, ct, title, wv in cands:
        print(f"[{nid}] {ct} «{title}»  widgets={wv}")


if isinstance(data, dict) and isinstance(data.get("nodes"), list):
    show_ui(data)
elif isinstance(data, dict):
    show_api(data)
else:
    print("unrecognized workflow format:", type(data))
