"""Camera capture helper (OpenCV; uses AVFoundation on macOS)."""
from __future__ import annotations

import cv2


def open_camera(cfg) -> cv2.VideoCapture:
    cam = cfg.camera
    cap = cv2.VideoCapture(cam.device_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam.frame_height)
    if not cap.isOpened():
        raise RuntimeError(
            f"cannot open camera index {cam.device_index}. "
            "On macOS, grant Camera permission to your terminal / IDE in "
            "System Settings → Privacy & Security → Camera, then retry."
        )
    return cap
