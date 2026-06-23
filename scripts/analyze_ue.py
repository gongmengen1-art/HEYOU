"""Assess whether the 'Use Everywhere' implicit wiring can be resolved to real links.

Prints the Anything-Everywhere source(s) and every UNCONNECTED typed input (the broadcast
targets), so we can judge if a programmatic UE->real-links repair is feasible.
"""
import json
import sys
from pathlib import Path

path = sys.argv[1] if len(sys.argv) > 1 else "workflows/cute_you_2.json"
d = json.loads(Path(path).read_text(encoding="utf-8"))
nodes = {n["id"]: n for n in d["nodes"]}
links = {l[0]: l for l in d.get("links", [])}


def label(nid):
    n = nodes.get(nid)
    if not n:
        return f"{nid}:<MISSING>"
    return f"{nid}:{n.get('type')}" + (f"«{n.get('title')}»" if n.get("title") else "")


def src_of(link_id):
    l = links.get(link_id)
    return label(l[1]) if l else f"link{link_id}:<dangling>"


print("=== Anything-Everywhere / Reroute source wiring ===")
for nid, n in nodes.items():
    t = (n.get("type") or "").lower()
    if "everywhere" in t or "reroute" in t:
        print(f"\n{label(nid)}")
        for inp in (n.get("inputs") or []):
            lk = inp.get("link")
            print(f"   in  {inp.get('name')}({inp.get('type')}) <- {src_of(lk) if lk else '(none)'}")
        for out in (n.get("outputs") or []):
            tgts = [label(links[l][3]) for l in (out.get("links") or []) if l in links]
            print(f"   out {out.get('name')}({out.get('type')}) -> {tgts}")

print("\n=== UNCONNECTED typed inputs (UE broadcast targets) ===")
WANT = {"MODEL", "CLIP", "VAE", "CONDITIONING", "CONTROL_NET", "INSIGHTFACE", "IMAGE"}
by_type: dict[str, list[str]] = {}
for nid, n in nodes.items():
    for inp in (n.get("inputs") or []):
        if inp.get("link") is None and (inp.get("type") in WANT):
            by_type.setdefault(inp["type"], []).append(f"{label(nid)}.{inp.get('name')}")
for typ, lst in sorted(by_type.items()):
    print(f"\n{typ} ({len(lst)}):")
    for x in lst:
        print("   ", x)
