#!/usr/bin/env python3
"""Headless self-check for auto-enroll + clustering — no camera, no InsightFace, no cost.

Drives Orchestrator._handle_face with synthetic faces (fake embeddings) and asserts the
key behaviors of the "see a face -> enroll & cluster" pipeline:
  1. same person across many frames -> ONE visitor, ONE generation (no duplicates)
  2. a revisit with a different view  -> merged into the SAME person (library grows)
  3. a stranger                       -> a NEW person
  4. an 'uncertain' face (sim in [match_low, match_high)) -> skipped (no enroll, no gen)
  5. a low-quality new face           -> not enrolled

Run:  uv run python scripts/smoke_autoenroll.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heyou import db                       # noqa: E402
from heyou.config import Config            # noqa: E402
from heyou.orchestrator import Orchestrator  # noqa: E402

rng = np.random.default_rng(7)


def unit() -> np.ndarray:
    v = rng.standard_normal(512).astype(np.float32)
    return (v / np.linalg.norm(v)).astype(np.float32)


def near(a: np.ndarray, w: float = 0.995) -> np.ndarray:
    """A near-identical view of `a` (for repeated frames of the same face)."""
    v = w * a + (1 - w) * unit()
    return (v / np.linalg.norm(v)).astype(np.float32)


def at_cosine(a: np.ndarray, target: float) -> np.ndarray:
    """A unit vector whose cosine to unit `a` is EXACTLY `target`."""
    r = unit()
    perp = r - np.dot(r, a) * a
    perp = perp / np.linalg.norm(perp)
    s = float(np.sqrt(max(0.0, 1.0 - target * target)))
    return (target * a + s * perp).astype(np.float32)


class FakeFace:
    def __init__(self, emb, det=0.9, pose=(0, 0, 0), bbox=(0, 0, 200, 200)):
        self.normed_embedding = emb
        self.det_score = det
        self.pose = np.array(pose, float)
        self.bbox = np.array(bbox, float)


class FakeService:
    """Records enqueues and simulates "generated today" so daily dedup can be tested."""
    def __init__(self):
        self.enqueued: list[int] = []
        self._done: set[int] = set()

    def done_today(self, pid): return pid in self._done
    def is_generating(self, pid): return False

    def enqueue(self, person):
        self.enqueued.append(person["id"])
        self._done.add(person["id"])
        return True


def make_orch(tmp):
    cfg = Config(storage={"data_dir": tmp})
    cfg.orchestration.debounce_sec = 100.0   # rapid re-detect must be deduped
    svc = FakeService()
    orch = Orchestrator(cfg, service=svc, recognizer=object(), enabled=True)
    return cfg, svc, orch


def main() -> int:
    frame = np.zeros((480, 640, 3), np.uint8)
    cfg, svc, orch = make_orch(tempfile.mkdtemp())
    A, B = unit(), unit()

    # 1) A walks in — 5 near-identical frames => one visitor, one generation
    for _ in range(5):
        orch._handle_face(frame, FakeFace(near(A)))
    people = db.list_people(cfg.db_path)
    assert len(people) == 1, f"expected 1 person, got {len(people)}"
    pid_a = people[0]["id"]
    assert svc.enqueued == [pid_a], f"expected 1 generation, got {svc.enqueued}"
    print(f"[1] A x5 frames -> 1 visitor #{pid_a}, 1 generation  OK")

    # 2) A revisits with a different view (cos 0.60) => merge + grow library, no re-gen
    orch._handle_face(frame, FakeFace(at_cosine(A, 0.60)))
    assert len(db.list_people(cfg.db_path)) == 1, "revisit must not create a new person"
    n = db.person_embedding_count(cfg.db_path, pid_a)
    assert n == 2, f"library should be 2, got {n}"
    assert svc.enqueued == [pid_a], "same-day revisit must not generate again"
    print(f"[2] A revisit (cos 0.60) -> 1 person, library {n}, no re-gen  OK")

    # 3) Stranger B => new person + one generation
    orch._handle_face(frame, FakeFace(near(B)))
    people = db.list_people(cfg.db_path)
    assert len(people) == 2, f"stranger should create a 2nd person, got {len(people)}"
    pid_b = [p["id"] for p in people if p["id"] != pid_a][0]
    assert svc.enqueued == [pid_a, pid_b], f"expected gens A,B; got {svc.enqueued}"
    print(f"[3] Stranger B -> new visitor #{pid_b}  OK")

    # 4) Uncertain band — on a FRESH not-yet-generated person, so a would-be MATCH would gen;
    #    proving "uncertain" skips both enroll and generation.
    cfg2, svc2, orch2 = make_orch(tempfile.mkdtemp())
    K = unit()
    orch2._handle_face(frame, FakeFace(near(K)))
    kid = db.list_people(cfg2.db_path)[0]["id"]
    svc2._done.discard(kid); svc2.enqueued.clear()          # pretend K's gen hasn't finished
    orch2._handle_face(frame, FakeFace(at_cosine(K, 0.44)))  # in [0.38, 0.50)
    assert len(db.list_people(cfg2.db_path)) == 1, "uncertain must not create a person"
    assert svc2.enqueued == [], "uncertain must not generate"
    print("[4] Uncertain face (cos 0.44) -> skipped (no person, no gen)  OK")

    # 5) Low-quality new face => not enrolled
    before = len(db.list_people(cfg.db_path))
    orch._handle_face(frame, FakeFace(unit(), det=0.2))
    assert len(db.list_people(cfg.db_path)) == before, "low-quality new face must be skipped"
    print("[5] Low-quality new face -> not enrolled  OK")

    print("\nALL AUTO-ENROLL CHECKS PASSED ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
