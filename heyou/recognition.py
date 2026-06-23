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


def best_match(embedding: np.ndarray, gallery: list[dict], threshold: float):
    """Return (person_dict, similarity) if best match >= threshold, else (None, best_sim)."""
    if not gallery:
        return None, 0.0
    mat = np.stack([g["embedding"] for g in gallery])  # (N, 512)
    sims = mat @ np.asarray(embedding, dtype=np.float32)  # (N,)
    idx = int(np.argmax(sims))
    best = float(sims[idx])
    if best >= threshold:
        return gallery[idx], best
    return None, best
