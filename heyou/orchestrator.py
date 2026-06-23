"""Camera recognition loop with runtime control.

Controls (thread-safe flags the loop reacts to within ~0.3s):
  - set_enabled(on): manual on/off (the console toggle button).
  - pause()/resume(): transient pause so the browser can grab the camera for enrollment.
The loop opens the camera only while (enabled and not paused), and releases it otherwise.
A paused state auto-resumes after _MAX_PAUSE as a safety net. Runs as a daemon thread,
auto-started by the web server; exposes a status for the console chip."""
from __future__ import annotations

import logging
import threading
import time

from . import db
from .camera import open_camera
from .config import Config
from .generation.service import GenerationService
from .recognition import FaceRecognizer, best_match

log = logging.getLogger("heyou.orchestrator")


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
        self._gallery_loaded_at = time.monotonic()
        self._last_seen: dict[int, float] = {}
        self._last_reco = 0.0
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
            self._gallery_loaded_at = time.monotonic()

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
        if self.service.enqueue(person):
            log.info("✓ %s recognized (sim=%.3f) → queued", person["name"], sim)

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
                        log.info("recognition camera opened (#%d), %d enrolled", idx, len(self.gallery))
                    except Exception as e:  # noqa: BLE001
                        self.status, self.status_detail = "error", str(e)
                        cap = None
                        log.error("camera open failed: %s (retry in 5s)", e)
                        self._stop.wait(5)
                        continue

                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.05)
                    continue
                now = time.monotonic()
                if now - self._last_reco < self.cfg.recognition.recognize_interval_sec:
                    time.sleep(min_interval)
                    continue
                self._last_reco = now
                self._maybe_reload_gallery()
                if not self.gallery:
                    continue
                for face in self.recognizer.detect(frame):
                    if self.recognizer.face_short_side(face) < self.cfg.recognition.min_face_px:
                        continue
                    person, sim = best_match(face.normed_embedding, self.gallery,
                                             self.cfg.recognition.match_threshold)
                    if person is not None:
                        self._consider(person, sim)
        finally:
            if cap is not None:
                cap.release()
            self.status = "stopped"
            log.info("recognition stopped")


def run(cfg: Config) -> None:
    from .logging_setup import setup_logging
    setup_logging(cfg)
    Orchestrator(cfg).run()
