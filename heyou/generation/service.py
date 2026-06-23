"""Shared generation service: ONE background worker for both camera-triggered and manual
(web) generations. Tracks in-flight people and today's completions so the camera loop and
the console agree on state."""
from __future__ import annotations

import logging
import queue
import random
import threading
import time

from .. import db
from ..printing import print_output
from ..styles import build_prompt, random_style
from .base import create_backend

log = logging.getLogger("heyou.generation")


class GenerationService:
    def __init__(self, cfg, backend=None):
        self.cfg = cfg
        try:
            self.backend = backend or create_backend(cfg)
        except Exception as e:  # noqa: BLE001
            log.error("backend init failed: %s", e)
            self.backend = None
        self._jobs: "queue.Queue[tuple]" = queue.Queue()
        self._inflight: dict[int, int] = {}   # job id -> person id
        self._done_today: dict[int, str] = {}  # person id -> date
        self._lock = threading.Lock()
        self._counter = 0
        self._rng = random.Random()
        self._stop = threading.Event()
        threading.Thread(target=self._worker, name="genservice", daemon=True).start()

    # ---- state queries -----------------------------------------------------
    def inflight_pids(self) -> set[int]:
        with self._lock:
            return set(self._inflight.values())

    def is_generating(self, pid: int) -> bool:
        with self._lock:
            return pid in self._inflight.values()

    def done_today(self, pid: int) -> bool:
        return self._done_today.get(pid) == db.today_str()

    # ---- enqueue -----------------------------------------------------------
    def enqueue(self, person: dict) -> bool:
        """Queue a generation for `person`; returns False if one is already in flight."""
        pid = person["id"]
        with self._lock:
            if pid in self._inflight.values():
                return False
            self._counter += 1
            jid = self._counter
            self._inflight[jid] = pid
        seed = self._rng.randint(1, 2_000_000_000)
        style = random_style(self._rng)
        self._jobs.put((jid, dict(person), seed, style))
        log.info("queued generation for %s (seed %s)", person.get("name"), seed)
        return True

    # ---- worker ------------------------------------------------------------
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                jid, person, seed, style = self._jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            pid, name, photo = person["id"], person.get("name"), person["photo_path"]
            try:
                if self.backend is None:
                    raise RuntimeError("generation backend unavailable")
                t0 = time.monotonic()
                log.info("→ generating for %s…", name)
                img = self.backend.generate(photo, seed, {"prompt": build_prompt(style), **style})
                out = self.cfg.output_dir / f"{pid}_{seed}.png"
                out.write_bytes(img)
                status = "generated"
                if self.cfg.printing.enabled:
                    ok, detail = print_output(str(out), self.cfg.printing)
                    status = "printed" if ok else "print_failed"
                    log.info("  print: %s (%s)", status, detail)
                db.add_print_log(self.cfg.db_path, pid, str(out), status, f"seed={seed}")
                db.mark_printed(self.cfg.db_path, pid, db.today_str())
                self._done_today[pid] = db.today_str()
                log.info("  %s %s in %.0fs -> %s", name, status, time.monotonic() - t0, out)
            except Exception as e:  # noqa: BLE001 — keep the worker alive
                log.error("  generation failed for %s: %s", name, e)
                db.add_print_log(self.cfg.db_path, pid, None, "failed", str(e))
            finally:
                with self._lock:
                    self._inflight.pop(jid, None)
                self._jobs.task_done()

    def stop(self) -> None:
        self._stop.set()
