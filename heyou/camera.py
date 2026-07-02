"""Camera capture helper (OpenCV). Uses AVFoundation on macOS and DirectShow on Windows."""
from __future__ import annotations

import sys

import cv2


def open_camera(cfg) -> cv2.VideoCapture:
    cam = cfg.camera
    if sys.platform.startswith("win"):
        # DirectShow is far more reliable than the default MSMF backend on Windows
        # (faster open, fewer hangs, honors width/height).
        cap = cv2.VideoCapture(cam.device_index, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(cam.device_index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, cam.frame_width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cam.frame_height)
    if not cap.isOpened():
        if sys.platform.startswith("win"):
            hint = ("On Windows: allow camera access in Settings → Privacy & security → "
                    "Camera (incl. 'Let desktop apps access your camera'), close any app "
                    "using the camera, and check the device_index.")
        elif sys.platform == "darwin":
            hint = ("On macOS, grant Camera permission to your terminal / IDE in "
                    "System Settings → Privacy & Security → Camera, then retry.")
        else:
            hint = "Check the device_index and that no other app holds the camera."
        raise RuntimeError(f"cannot open camera index {cam.device_index}. {hint}")
    return cap
