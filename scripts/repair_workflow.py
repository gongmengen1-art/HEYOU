"""Repair the Cute You 2 workflow for RunningHub API use.

What it does (deterministic, based on analyze_ue.py findings):
  1. Resolve 'Anything Everywhere3' implicit broadcasts into explicit links:
       736(MODEL) -> 740.model, 932.model
       736(CLIP)  -> 791.clip, 712.clip, 713.clip
       927(VAE)   -> 661.optional_vae, 354.optional_vae
  2. Delete the Anything-Everywhere node (655) — no longer needed once links are explicit.
  3. Drop all dangling links (to phantom nodes 363/658/768/870 and the deleted 655).

Writes workflows/cute_you_2.fixed.json. Node IDs are preserved.
"""
import json
from pathlib import Path

SRC = Path("workflows/cute_you_2.json")
DST = Path("workflows/cute_you_2.fixed.json")

d = json.loads(SRC.read_text(encoding="utf-8"))
nodes = {n["id"]: n for n in d["nodes"]}
links = d["links"]

# UE resolution: (src_node, out_type) -> list of (dst_node, input_name)
RESOLVE = [
    (736, "MODEL", [(740, "model"), (932, "model")]),
    (736, "CLIP",  [(791, "clip"), (712, "clip"), (713, "clip")]),
    (927, "VAE",   [(661, "optional_vae"), (354, "optional_vae")]),
]


def out_slot(node, typ):
    for i, o in enumerate(node.get("outputs", [])):
        if o.get("type") == typ:
            return i, o
    raise KeyError(f"node {node['id']} has no {typ} output")


def in_slot(node, name):
    for i, inp in enumerate(node.get("inputs", [])):
        if inp.get("name") == name:
            return i, inp
    raise KeyError(f"node {node['id']} has no input '{name}'")


next_id = max(l[0] for l in links) + 1
added = []
for src_id, typ, targets in RESOLVE:
    sn = nodes[src_id]
    s_slot, s_out = out_slot(sn, typ)
    if s_out.get("links") is None:
        s_out["links"] = []
    for dst_id, in_name in targets:
        dn = nodes[dst_id]
        d_slot, d_in = in_slot(dn, in_name)
        if d_in.get("link") is not None:
            continue  # already wired, leave it
        lid = next_id
        next_id += 1
        links.append([lid, src_id, s_slot, dst_id, d_slot, typ])
        d_in["link"] = lid
        s_out["links"].append(lid)
        added.append((lid, src_id, typ, dst_id, in_name))

# Delete the Anything-Everywhere node
d["nodes"] = [n for n in d["nodes"] if n["id"] != 655]
present = {n["id"] for n in d["nodes"]}

# Drop dangling links (endpoint missing, e.g. phantom nodes or the removed 655)
keep, removed = [], []
for l in links:
    (removed if (l[1] not in present or l[3] not in present) else keep).append(l)
d["links"] = keep
removed_ids = {l[0] for l in removed}

# Clean removed link references off the surviving nodes
for n in d["nodes"]:
    for inp in (n.get("inputs") or []):
        if inp.get("link") in removed_ids:
            inp["link"] = None
    for out in (n.get("outputs") or []):
        if out.get("links"):
            out["links"] = [x for x in out["links"] if x not in removed_ids]

DST.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"added {len(added)} explicit links:")
for a in added:
    print("   ", a)
print(f"\nremoved {len(removed_ids)} dangling links: {sorted(removed_ids)}")
print(f"deleted node 655 (Anything Everywhere3)")
print(f"\nnodes: {len(d['nodes'])}  links: {len(d['links'])}")
print(f"wrote {DST}")
