"""Face detection + embedding via InsightFace, plus gallery matching."""
from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)


class FaceRecognizer:
    def __init__(self, model_pack="buffalo_l", providers=None, ctx_id=-1, det_size=640):
        from insightface.app import FaceAnalysis  # lazy import (heavy, pulls onnxruntime)

        self.app = FaceAnalysis(name=model_pack, providers=providers or ["CPUExecutionProvider"])
        self.app.prepare(ctx_id=ctx_id, det_size=(det_size, det_size))
        log.info("FaceAnalysis ready (pack=%s, providers=%s)", model_pack, providers)

    def detect(self, image_bgr: np.ndarray):
        """Return a list of insightface Face objects (each has .bbox, .normed_embedding)."""
        return self.app.get(image_bgr)

    @staticmethod
    def face_short_side(face) -> float:
        x1, y1, x2, y2 = face.bbox
        return float(min(x2 - x1, y2 - y1))

    def largest_face(self, image_bgr: np.ndarray):
        faces = self.detect(image_bgr)
        if not faces:
            return None
        return max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))

    def embed_file(self, path: str | Path):
        """Return (normed_embedding float32, face) or (None, error_message)."""
        img = cv2.imread(str(path))
        if img is None:
            return None, f"cannot read image: {path}"
        face = self.largest_face(img)
        if face is None:
            return None, "no face detected"
        return np.asarray(face.normed_embedding, dtype=np.float32), face


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    # embeddings are L2-normalized, so dot product == cosine similarity
    return float(np.dot(a, b))


def build_index(gallery: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Flatten a multi-embedding gallery into one matrix for fast matching.
    Returns (matrix (M,512), pids (M,)) where row i belongs to person pids[i]."""
    mats, pids = [], []
    for g in gallery:
        e = g["embeddings"]
        mats.append(e)
        pids.extend([g["id"]] * len(e))
    if not mats:
        return np.zeros((0, 512), dtype=np.float32), np.zeros((0,), dtype=np.int64)
    return np.vstack(mats).astype(np.float32), np.asarray(pids, dtype=np.int64)


def best_match(embedding: np.ndarray, gallery: list[dict], threshold: float):
    """Legacy single-threshold match against a multi-embedding gallery.
    Returns (person_dict, similarity) if best >= threshold, else (None, best_sim)."""
    matrix, pids = build_index(gallery)
    decision, pid, sim = classify(embedding, matrix, pids, threshold, threshold)
    if decision == "match":
        person = next((g for g in gallery if g["id"] == pid), None)
        return person, sim
    return None, sim


def classify(embedding: np.ndarray, matrix: np.ndarray, pids: np.ndarray,
             t_high: float, t_low: float) -> tuple[str, int | None, float]:
    """Two-threshold decision against the flat index (matrix, pids):
      best_sim >= t_high  -> ("match", pid, sim)   same person, merge/generate
      best_sim <  t_low   -> ("new",   None, sim)  new person
      otherwise           -> ("uncertain", None, sim)  skip (don't enroll/generate)
    On an empty index, returns ("new", None, 0.0)."""
    if matrix.shape[0] == 0:
        return "new", None, 0.0
    sims = matrix @ np.asarray(embedding, dtype=np.float32)  # (M,)
    i = int(np.argmax(sims))
    best = float(sims[i])
    if best >= t_high:
        return "match", int(pids[i]), best
    if best < t_low:
        return "new", None, best
    return "uncertain", None, best
