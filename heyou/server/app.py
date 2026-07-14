"""Bar-owner demo console (FastAPI).

Auto-starts the camera recognition service together with the web server (and stops it on
shutdown). Exposes engine / printer / recognition connection status. Camera-triggered and
manual ("立即生成") generations share one GenerationService, so state is consistent."""
from __future__ import annotations

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .. import db
from ..config import load_config
from ..generation.service import GenerationService
from ..logging_setup import setup_logging
from ..printing import backend_status, print_output
from ..recognition import FaceRecognizer

log = logging.getLogger("heyou.server")

cfg = load_config()
cfg.ensure_dirs()
setup_logging(cfg)
db.init_db(cfg.db_path)
try:
    db.purge_old_history(cfg.db_path, cfg.storage.history_retention_days, cfg.output_dir)
    n = db.purge_inactive_visitors(cfg.db_path, cfg.storage.visitor_retention_days)
    if n:
        log.info("purged %d inactive auto-enrolled visitor(s)", n)
except Exception as e:  # noqa: BLE001
    log.warning("history/visitor purge on startup failed: %s", e)

STATIC_DIR = Path(__file__).resolve().parent / "static"

_service = GenerationService(cfg)
_recognizer: FaceRecognizer | None = None
_recognition = None  # Orchestrator instance

_DISABLED = os.environ.get("HEYOU_DISABLE_RECOGNITION") == "1"


def recognizer() -> FaceRecognizer:
    """Shared face model — used by both enrollment and the recognition loop."""
    global _recognizer
    if _recognizer is None:
        _recognizer = FaceRecognizer(
            model_pack=cfg.recognition.model_pack,
            providers=cfg.recognition.providers,
            ctx_id=cfg.recognition.ctx_id,
            det_size=cfg.recognition.det_size,
        )
    return _recognizer


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _recognition
    if not _DISABLED:
        try:
            from ..orchestrator import Orchestrator
            _recognition = Orchestrator(cfg, service=_service, recognizer=recognizer(),
                                        enabled=cfg.recognition.autostart)
            threading.Thread(target=_recognition.run, name="recognition", daemon=True).start()
            log.info("recognition controller started (enabled=%s)", cfg.recognition.autostart)
        except Exception as e:  # noqa: BLE001
            log.error("recognition start failed: %s", e)
    yield
    if _recognition is not None:
        _recognition.stop()
        log.info("recognition stopped with the server")


app = FastAPI(title="HEYOU console", lifespan=lifespan)


# ---- cached status + purge throttle ---------------------------------------
_cache: dict[str, tuple] = {"engine": (0.0, None), "printer": (0.0, None)}
_ENGINE_TTL, _PRINTER_TTL = 20.0, 10.0
_last_purge = time.monotonic()
_PURGE_INTERVAL = 3600.0


def _engine_status() -> dict:
    now = time.monotonic()
    ts, val = _cache["engine"]
    if val is None or now - ts > _ENGINE_TTL:
        try:
            connected = bool(_service.backend and _service.backend.ping())
        except Exception:  # noqa: BLE001
            connected = False
        val = {"name": cfg.generation.backend, "connected": connected}
        _cache["engine"] = (now, val)
    return val


def _printer_status() -> dict:
    now = time.monotonic()
    ts, val = _cache["printer"]
    if val is None or now - ts > _PRINTER_TTL:
        val = backend_status(cfg.printing)
        _cache["printer"] = (now, val)
    return val


def _recognition_status() -> dict:
    if _recognition is None:
        return {"status": "disabled", "detail": "", "enrolled": 0}
    return _recognition.status_dict()


def _maybe_purge() -> None:
    global _last_purge
    now = time.monotonic()
    if now - _last_purge > _PURGE_INTERVAL:
        _last_purge = now
        try:
            db.purge_old_history(cfg.db_path, cfg.storage.history_retention_days, cfg.output_dir)
        except Exception as e:  # noqa: BLE001
            log.warning("history purge failed: %s", e)


# ---- endpoints ------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/status")
def api_status() -> dict:
    _maybe_purge()
    return {
        "engine": _engine_status(),
        "printer": _printer_status(),
        "recognition": _recognition_status(),
    }


@app.post("/api/recognition/{action}")
def api_recognition(action: str) -> dict:
    """Runtime control: start | stop | pause | resume."""
    if _recognition is None:
        raise HTTPException(409, "recognition unavailable")
    if action == "start":
        _recognition.set_enabled(True)
    elif action == "stop":
        _recognition.set_enabled(False)
    elif action == "pause":
        _recognition.pause()
    elif action == "resume":
        _recognition.resume()
    else:
        raise HTTPException(400, "unknown action")
    return _recognition.status_dict()


@app.get("/api/people")
def api_people(page: int = 1, page_size: int | None = None) -> dict:
    ps = page_size or cfg.server.page_size
    page = max(1, page)
    rows, total = db.list_people_state(cfg.db_path, ps, (page - 1) * ps)
    today = db.today_str()
    inflight = _service.inflight_pids()
    items = []
    for r in rows:
        last_gen = r.get("last_gen_ts") or ""
        items.append({
            "id": r["id"],
            "name": r["name"],
            "last_print_date": r["last_print_date"],
            "last_output": Path(r["last_output"]).name if r.get("last_output") else None,
            "generated_today": last_gen[:10] == today,
            "generating": r["id"] in inflight,
        })
    pages = max(1, (total + ps - 1) // ps)
    return {"items": items, "page": page, "pages": pages, "total": total, "page_size": ps}


@app.post("/api/enroll")
async def api_enroll(name: str = Form(...), file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "无法解析图片")
    face = recognizer().largest_face(img)
    if face is None:
        raise HTTPException(400, "未检测到人脸，请换一张清晰的正脸照")
    emb = np.asarray(face.normed_embedding, dtype=np.float32)
    pid = db.add_person(cfg.db_path, name.strip(), emb, "", source="enroll")
    photo_path = cfg.enrolled_dir / f"{pid}.jpg"
    cv2.imwrite(str(photo_path), img)
    db.set_person_photo(cfg.db_path, pid, photo_path)
    log.info("enrolled #%d %s", pid, name)
    return {"id": pid, "name": name.strip()}


@app.get("/api/photo/{pid}")
def api_photo(pid: int):
    p = db.get_person(cfg.db_path, pid)
    if not p or not p["photo_path"] or not Path(p["photo_path"]).exists():
        raise HTTPException(404, "no photo")
    return FileResponse(p["photo_path"])


@app.delete("/api/people/{pid}")
def api_delete(pid: int) -> dict:
    p = db.get_person(cfg.db_path, pid)
    if p and p["photo_path"]:
        Path(p["photo_path"]).unlink(missing_ok=True)
    db.delete_person(cfg.db_path, pid)
    return {"ok": True}


@app.post("/api/generate/{pid}")
def api_generate(pid: int) -> dict:
    p = db.get_person(cfg.db_path, pid)
    if not p:
        raise HTTPException(404, "not found")
    queued = _service.enqueue(p)
    return {"name": p["name"], "queued": queued, "already": not queued}


@app.post("/api/print/{pid}")
def api_print(pid: int) -> dict:
    """Manually (re)print the person's latest generated cartoon — fallback for auto-print."""
    p = db.get_person(cfg.db_path, pid)
    if not p:
        raise HTTPException(404, "not found")
    out = db.person_last_output(cfg.db_path, pid)
    if not out or not Path(out).exists():
        raise HTTPException(400, "没有可打印的卡通图，请先生成")
    ok, detail = print_output(out, cfg.printing)
    db.add_print_log(cfg.db_path, pid, out, "reprinted" if ok else "reprint_failed", f"manual: {detail}")
    if not ok:
        raise HTTPException(500, f"打印失败：{detail}")
    return {"ok": True, "detail": detail}


@app.get("/api/history/{pid}")
def api_history(pid: int) -> list[dict]:
    if not db.get_person(cfg.db_path, pid):
        raise HTTPException(404, "not found")
    cutoff = db.cutoff_date(cfg.storage.history_retention_days)
    rows = db.person_history(cfg.db_path, pid, cutoff)
    return [{"ts": r["ts"], "status": r["status"],
             "output": Path(r["output_path"]).name if r["output_path"] else None} for r in rows]


@app.get("/api/output/{name}")
def api_output(name: str):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "bad name")
    p = cfg.output_dir / name
    if not p.exists():
        raise HTTPException(404, "not found")
    return FileResponse(p)
