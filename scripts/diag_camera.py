"""Camera diagnostic — isolate 'recognition never triggers' on a given machine.

The recognition loop can silently stall when the camera *opens* but never delivers
frames (a common DirectShow quirk on Windows, or a blocked camera-privacy setting):
`cap.isOpened()` is True, so no error is logged, yet `cap.read()` returns ok=False or
all-black frames forever. This script makes that visible: for each (index, backend) it
reports whether the camera opens, whether reads succeed, the frame size, and the mean
brightness (to catch all-black frames from a blocked/covered camera). With --detect it
also runs one InsightFace pass to confirm the model + onnxruntime provider work.

Run on the machine that fails:
    uv run python scripts/diag_camera.py            # probe indices 0,1,2 on all backends
    uv run python scripts/diag_camera.py --index 1  # probe only index 1
    uv run python scripts/diag_camera.py --detect    # also try a face-detection pass
"""
from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np


def backends() -> list[tuple[str, int]]:
    """(name, cv2 flag) camera backends to try, most-relevant-first per platform."""
    if sys.platform.startswith("win"):
        return [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF), ("ANY", cv2.CAP_ANY)]
    if sys.platform == "darwin":
        return [("AVFOUNDATION", cv2.CAP_AVFOUNDATION), ("ANY", cv2.CAP_ANY)]
    return [("V4L2", cv2.CAP_V4L2), ("ANY", cv2.CAP_ANY)]


def probe(index: int, name: str, flag: int, width: int, height: int,
          reads: int = 15) -> dict:
    """Open one (index, backend), try to read `reads` frames, and summarize."""
    res = {"index": index, "backend": name, "opened": False, "read_ok": 0,
           "reads": reads, "shape": None, "brightness": None, "error": None}
    cap = None
    try:
        cap = cv2.VideoCapture(index, flag)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        res["opened"] = bool(cap.isOpened())
        if not res["opened"]:
            return res
        brights: list[float] = []
        for _ in range(reads):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size:
                res["read_ok"] += 1
                res["shape"] = tuple(frame.shape)
                brights.append(float(np.asarray(frame).mean()))
            time.sleep(0.03)
        if brights:
            res["brightness"] = round(sum(brights) / len(brights), 1)
    except Exception as e:  # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
    finally:
        if cap is not None:
            cap.release()
    return res


def verdict(r: dict) -> str:
    if r["error"]:
        return f"ERROR — {r['error']}"
    if not r["opened"]:
        return "cannot open (index/backend not available, or camera busy)"
    if r["read_ok"] == 0:
        return "OPENS BUT DELIVERS NO FRAMES  ← this is the silent-stall case"
    if r["brightness"] is not None and r["brightness"] < 2.0:
        return (f"reads OK but frames are ALL BLACK (brightness={r['brightness']}) "
                "← camera blocked/covered or privacy setting off")
    return f"OK — {r['read_ok']}/{r['reads']} frames, {r['shape']}, brightness={r['brightness']}"


def try_detect(index: int, flag: int, width: int, height: int) -> None:
    """Grab one good frame and run InsightFace once, to confirm model + provider."""
    print("\n--- InsightFace detection check ---")
    try:
        from heyou.config import load_config
        from heyou.recognition import FaceRecognizer
    except Exception as e:  # noqa: BLE001
        print(f"  (skipped: cannot import heyou — {e})")
        return
    cfg = load_config()
    cap = cv2.VideoCapture(index, flag)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    frame = None
    for _ in range(20):
        ok, f = cap.read()
        if ok and f is not None and f.size:
            frame = f
            break
        time.sleep(0.05)
    cap.release()
    if frame is None:
        print("  no frame to test on — fix the camera first (see the table above)")
        return
    try:
        t0 = time.monotonic()
        rec = FaceRecognizer(
            model_pack=cfg.recognition.model_pack,
            providers=cfg.recognition.providers,
            ctx_id=cfg.recognition.ctx_id,
            det_size=cfg.recognition.det_size,
        )
        faces = rec.detect(frame)
        dt = time.monotonic() - t0
        print(f"  providers={cfg.recognition.providers}  det_size={cfg.recognition.det_size}")
        print(f"  detected {len(faces)} face(s) in {dt:.1f}s "
              f"(first call includes model load)")
        if faces:
            print("  → recognition works; if the app still won't trigger, the camera the "
                  "app opens differs from this one, or the 识别 toggle is off.")
        else:
            print("  → model runs but saw no face in this frame; make sure a face is in "
                  "view, well-lit, and large enough (min_face_px).")
    except Exception as e:  # noqa: BLE001
        print(f"  InsightFace/onnxruntime FAILED to init or run: {type(e).__name__}: {e}")
        print("  → this is why recognition never triggers; fix the provider/model, not the camera.")


def main() -> int:
    ap = argparse.ArgumentParser(description="Diagnose camera frame delivery for HEYOU.")
    ap.add_argument("--index", type=int, default=None,
                    help="probe only this camera index (default: 0,1,2)")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--detect", action="store_true",
                    help="also run one InsightFace pass on a captured frame")
    args = ap.parse_args()

    indices = [args.index] if args.index is not None else [0, 1, 2]
    print(f"platform={sys.platform}  opencv={cv2.__version__}")
    print(f"probing indices={indices} at {args.width}x{args.height}\n")

    good: tuple[int, int] | None = None
    for index in indices:
        for name, flag in backends():
            r = probe(index, name, flag, args.width, args.height)
            print(f"index {index:>2}  {name:<12}  {verdict(r)}")
            if good is None and r["read_ok"] > 0 and (r["brightness"] or 0) >= 2.0:
                good = (index, flag)
        print()

    if good is None:
        print("No (index, backend) delivered usable frames.")
        print("→ On Windows: Settings → Privacy & security → Camera → turn ON both "
              "'Camera access' and 'Let desktop apps access your camera'; close any app "
              "(Teams/Zoom/OBS/Camera) holding the camera; try a different device_index.")
    else:
        idx, _ = good
        print(f"Usable camera: index {idx}. Set  camera.device_index: {idx}  in config.yaml "
              "if it isn't already.")

    if args.detect:
        flag = good[1] if good else backends()[0][1]
        idx = good[0] if good else (args.index if args.index is not None else 0)
        try_detect(idx, flag, args.width, args.height)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.parent.as_posix())
    raise SystemExit(main())
