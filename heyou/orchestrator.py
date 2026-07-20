"""Camera recognition loop with runtime control.

Controls (thread-safe flags the loop reacts to within ~0.3s):
  - set_enabled(on): manual on/off (the console toggle button).
  - pause()/resume(): transient pause so the browser can grab the camera for enrollment.
The loop opens the camera only while (enabled and not paused), and releases it otherwise.
A paused state auto-resumes after _MAX_PAUSE as a safety net. Runs as a daemon thread,
auto-started by the web server; exposes a status for the console chip."""
from __future__ import annotations

import datetime as _dt
import logging
import threading
import time

import cv2
import numpy as np

from . import db
from .camera import open_camera
from .config import Config
from .generation.service import GenerationService
from .recognition import FaceRecognizer, build_index, classify

log = logging.getLogger("heyou.orchestrator")


def _read_fail_hint() -> str:
    import sys
    if sys.platform.startswith("win"):
        return ("check Settings → Privacy & security → Camera ('Let desktop apps access "
                "your camera'), close apps holding the camera, try another device_index "
                "— run: uv run python scripts/diag_camera.py")
    return "close other apps using the camera and check camera.device_index"


class Orchestrator:
    _MAX_PAUSE = 120.0  # auto-resume if a pause is never lifted (e.g. browser tab closed)

    def __init__(self, cfg: Config, service: GenerationService | None = None,
                 recognizer: FaceRecognizer | None = None, enabled: bool = True):
        self.cfg = cfg
        cfg.ensure_dirs()
        db.init_db(cfg.db_path)
        self.recognizer = recognizer or FaceRecognizer(
            model_pack=cfg.recognition.model_pack,
            providers=cfg.recognition.providers,
            ctx_id=cfg.recognition.ctx_id,
            det_size=cfg.recognition.det_size,
        )
        self.service = service or GenerationService(cfg)
        self.gallery = db.get_gallery(cfg.db_path)
        self._matrix, self._pids = build_index(self.gallery)
        self._gallery_loaded_at = time.monotonic()
        self._last_seen: dict[int, float] = {}
        self._last_reco = 0.0
        self._read_fails = 0                       # consecutive cap.read() failures (silent-stall guard)
        self._last_read_warn = 0.0
        self._got_frame = False                    # logged once when frames start flowing after an open
        self._gen_today = 0                       # generations enqueued today (for global cap)
        self._gen_today_date = db.today_str()
        self._stop = threading.Event()
        self._enabled = enabled
        self._paused = False
        self._paused_at = 0.0
        self.status = "starting" if enabled else "off"
        self.status_detail = ""

    # ---- controls ----------------------------------------------------------
    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        log.info("recognition %s", "enabled" if on else "disabled")

    def pause(self) -> None:
        self._paused = True
        self._paused_at = time.monotonic()
        log.info("recognition paused (camera released for enrollment)")

    def resume(self) -> None:
        self._paused = False
        log.info("recognition resumed")

    def stop(self) -> None:
        self._stop.set()

    def status_dict(self) -> dict:
        return {"status": self.status, "detail": self.status_detail,
                "enrolled": len(self.gallery), "enabled": self._enabled, "paused": self._paused}

    # ---- internals ---------------------------------------------------------
    def _maybe_reload_gallery(self) -> None:
        if time.monotonic() - self._gallery_loaded_at >= self.cfg.orchestration.gallery_reload_sec:
            self.gallery = db.get_gallery(self.cfg.db_path)
            self._matrix, self._pids = build_index(self.gallery)
            self._gallery_loaded_at = time.monotonic()

    def _rebuild_index(self) -> None:
        self._matrix, self._pids = build_index(self.gallery)

    def _person_by_id(self, pid: int) -> dict | None:
        return next((g for g in self.gallery if g["id"] == pid), None)

    def _cap_ok(self) -> bool:
        cap = self.cfg.orchestration.global_daily_cap
        if cap <= 0:
            return True
        today = db.today_str()
        if self._gen_today_date != today:
            self._gen_today_date, self._gen_today = today, 0
        return self._gen_today < cap

    def _face_quality_ok(self, face) -> bool:
        """Gate a face before it's allowed to enroll/append (keeps bad crops out of the
        auto-built library): detector confidence + head pose within limits."""
        if float(getattr(face, "det_score", 1.0) or 1.0) < self.cfg.recognition.enroll_min_det_score:
            return False
        pose = getattr(face, "pose", None)      # [pitch, yaw, roll] degrees, if the pose model ran
        if pose is not None:
            lim = self.cfg.recognition.enroll_max_pose_deg
            try:
                if abs(float(pose[0])) > lim or abs(float(pose[1])) > lim:
                    return False
            except (IndexError, TypeError, ValueError):
                pass
        return True

    def _save_crop(self, frame, face, path) -> None:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = (int(v) for v in face.bbox)
        mx, my = int((x2 - x1) * 0.25), int((y2 - y1) * 0.25)   # a little margin around the face
        x1, y1 = max(0, x1 - mx), max(0, y1 - my)
        x2, y2 = min(w, x2 + mx), min(h, y2 + my)
        crop = frame[y1:y2, x1:x2]
        if crop.size:
            cv2.imwrite(str(path), crop)

    def _enroll_new(self, frame, face, emb: np.ndarray, sim: float) -> dict:
        """Create a new visitor from an unmatched face and seed their feature library."""
        name = _dt.datetime.now().strftime("访客 %m%d-%H%M")
        pid = db.add_person(self.cfg.db_path, name, emb, "", source="auto", sim=sim)
        path = self.cfg.visitors_dir / f"{pid}.jpg"
        self._save_crop(frame, face, path)
        db.set_person_photo(self.cfg.db_path, pid, path)
        person = {"id": pid, "name": name, "photo_path": str(path),
                  "last_print_date": None, "source": "auto",
                  "embeddings": emb[None, :].astype(np.float32)}
        self.gallery.append(person)          # visible to matching IMMEDIATELY (no 10s wait)
        self._rebuild_index()
        log.info("＋ new visitor #%d %s (best_sim=%.3f)", pid, name, sim)
        return person

    def _maybe_append(self, person: dict, frame, face, emb: np.ndarray, sim: float) -> None:
        """Grow a matched person's feature library, if the capture adds value and there's room."""
        if sim >= self.cfg.orchestration.append_dup_sim:
            return                            # too similar to an existing view — redundant
        cap = self.cfg.orchestration.max_embeddings_per_person
        n = len(person["embeddings"])
        if cap and n >= cap:
            return                            # library full
        path = self.cfg.visitors_dir / f"{person['id']}_{n}.jpg"
        self._save_crop(frame, face, path)
        db.add_embedding(self.cfg.db_path, person["id"], emb, path, sim)
        person["embeddings"] = np.vstack([person["embeddings"], emb[None, :]]).astype(np.float32)
        self._rebuild_index()
        log.info("＋ grew library of #%d (%d→%d, sim=%.3f)", person["id"], n, n + 1, sim)

    def _handle_face(self, frame, face) -> None:
        """Decide what to do with one detected face: enroll a new visitor, grow a known
        person's library, or skip — then consider it for generation. The whole per-face
        policy lives here so the camera loop stays a thin driver."""
        rc = self.cfg.recognition
        if FaceRecognizer.face_short_side(face) < rc.min_face_px:
            return
        emb = np.asarray(face.normed_embedding, dtype=np.float32)
        decision, pid, sim = classify(emb, self._matrix, self._pids, rc.match_high, rc.match_low)
        if decision == "uncertain":
            return                              # ambiguous — don't enroll or generate
        if decision == "new":
            if not self.cfg.orchestration.auto_enroll:
                return                          # legacy mode: only known people generate
            if not self._face_quality_ok(face):
                return                          # bad crop — don't create a junk visitor
            person = self._enroll_new(frame, face, emb, sim)
            self._consider(person, sim)
        else:                                   # "match" -> known person
            person = self._person_by_id(pid)
            if person is None:
                return
            if self._face_quality_ok(face):
                self._maybe_append(person, frame, face, emb, sim)
            self._consider(person, sim)

    def _consider(self, person: dict, sim: float) -> None:
        pid = person["id"]
        now = time.monotonic()
        if now - self._last_seen.get(pid, -1e9) < self.cfg.orchestration.debounce_sec:
            return
        self._last_seen[pid] = now
        if person["last_print_date"] == db.today_str() or self.service.done_today(pid):
            log.info("· %s (sim=%.3f) already generated today, skip", person["name"], sim)
            return
        if self.service.is_generating(pid):
            return
        if not self._cap_ok():
            log.info("· global daily cap (%d) reached — skip %s",
                     self.cfg.orchestration.global_daily_cap, person["name"])
            return
        if self.service.enqueue(person):
            self._gen_today += 1
            log.info("✓ %s (sim=%.3f) → queued", person["name"], sim)

    def run(self) -> None:
        idx = self.cfg.camera.device_index
        min_interval = 1.0 / max(self.cfg.camera.fps_limit, 1.0)
        cap = None
        log.info("recognition controller running (enabled=%s, backend=%s, printing=%s)",
                 self._enabled, self.service.backend.name if self.service.backend else "none",
                 "ON" if self.cfg.printing.enabled else "off")
        try:
            while not self._stop.is_set():
                if self._paused and time.monotonic() - self._paused_at > self._MAX_PAUSE:
                    self._paused = False
                    log.info("recognition auto-resumed (pause timeout)")

                if not (self._enabled and not self._paused):       # inactive → release camera, idle
                    if cap is not None:
                        cap.release()
                        cap = None
                    self.status = "off" if not self._enabled else "paused"
                    self._stop.wait(0.3)
                    continue

                if cap is None:                                    # (re)open camera
                    try:
                        cap = open_camera(self.cfg)
                        self.status, self.status_detail = "running", f"camera #{idx}"
                        self._got_frame, self._read_fails = False, 0
                        log.info("recognition camera opened (#%d), %d enrolled", idx, len(self.gallery))
                    except Exception as e:  # noqa: BLE001
                        self.status, self.status_detail = "error", str(e)
                        cap = None
                        log.error("camera open failed: %s (retry in 5s)", e)
                        self._stop.wait(5)
                        continue

                ok, frame = cap.read()
                if not ok or frame is None:
                    self._read_fails += 1
                    tnow = time.monotonic()
                    if self._read_fails == 1 or tnow - self._last_read_warn > 5.0:
                        self._last_read_warn = tnow
                        self.status_detail = f"camera #{idx}: no frames"
                        log.warning("camera #%d opened but read() failed (%d in a row) — no "
                                    "frames, recognition can't trigger; %s",
                                    idx, self._read_fails, _read_fail_hint())
                    time.sleep(0.05)
                    continue
                if self._read_fails:
                    log.info("camera #%d recovered after %d failed read(s)", idx, self._read_fails)
                    self._read_fails = 0
                if not self._got_frame:
                    self._got_frame = True
                    h, w = frame.shape[:2]
                    self.status_detail = f"camera #{idx} ({w}x{h})"
                    log.info("camera #%d delivering frames (%dx%d)", idx, w, h)
                now = time.monotonic()
                if now - self._last_reco < self.cfg.recognition.recognize_interval_sec:
                    time.sleep(min_interval)
                    continue
                self._last_reco = now
                self._maybe_reload_gallery()
                for face in self.recognizer.detect(frame):
                    self._handle_face(frame, face)
        finally:
            if cap is not None:
                cap.release()
            self.status = "stopped"
            log.info("recognition stopped")


def run(cfg: Config) -> None:
    from .logging_setup import setup_logging
    setup_logging(cfg)
    Orchestrator(cfg).run()
