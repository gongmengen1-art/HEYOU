"""Offline placeholder backend.

Stylizes the enrolled portrait so the full pipeline (recognize -> generate -> save ->
print) is testable without RunningHub — no network, no cost. This is NOT identity-
preserving generation; it just proves the wiring. Phase 1 only.
"""
from __future__ import annotations

import cv2
import numpy as np


def _cartoonify(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    try:
        sigma_s = float(40 + rng.integers(0, 60))  # vary the look with the seed
        sigma_r = float(0.35 + rng.random() * 0.30)
        return cv2.stylization(img, sigma_s=sigma_s, sigma_r=sigma_r)
    except Exception:
        # fallback if the photo module isn't available: bilateral + edge overlay
        color = cv2.bilateralFilter(img, 9, 250, 250)
        gray = cv2.medianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 5)
        edges = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 9
        )
        return cv2.bitwise_and(color, cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR))


class MockBackend:
    name = "mock"

    def __init__(self, cfg=None):
        self.cfg = cfg

    def generate(self, portrait_path: str, seed: int, style_params: dict) -> bytes:
        img = cv2.imread(str(portrait_path))
        if img is None:
            raise FileNotFoundError(f"cannot read portrait: {portrait_path}")
        rng = np.random.default_rng(seed)
        out = _cartoonify(img, rng)
        cv2.putText(out, f"MOCK  seed={seed}", (12, 34), cv2.FONT_HERSHEY_SIMPLEX,
                    0.9, (0, 0, 255), 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".png", out)
        if not ok:
            raise RuntimeError("failed to encode mock image")
        return buf.tobytes()

    def ping(self) -> bool:
        return True
