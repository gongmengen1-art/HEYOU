"""Typed configuration loaded from config.yaml (pydantic v2)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ComfyuiCfg(BaseModel):
    comfyui_url: str | None = None
    comfyui_api_key: str | None = None
    runninghub_api_key: str | None = None
    runninghub_concurrent_limit: int = 1
    runninghub_instance_type: str | None = None


class RunningHubCfg(BaseModel):
    base_url: str = "https://www.runninghub.cn"
    workflow_id: str = ""
    poll_interval_sec: float = 3.0
    timeout_sec: float = 240.0
    input_image_node_id: str = ""
    seed_node_id: str = ""
    prompt_node_id: str = ""


class GenerationCfg(BaseModel):
    backend: str = "mock"  # "mock" | "runninghub"
    runninghub: RunningHubCfg = Field(default_factory=RunningHubCfg)


class CameraCfg(BaseModel):
    device_index: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    fps_limit: float = 8.0


class RecognitionCfg(BaseModel):
    model_pack: str = "buffalo_l"
    providers: list[str] = Field(default_factory=lambda: ["CPUExecutionProvider"])
    ctx_id: int = -1
    det_size: int = 640
    match_threshold: float = 0.45
    min_face_px: int = 90
    recognize_interval_sec: float = 0.4
    autostart: bool = True


class OrchestrationCfg(BaseModel):
    debounce_sec: float = 5.0
    daily_limit: int = 1
    gallery_reload_sec: float = 10.0


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    page_size: int = 8


class PixcutCfg(BaseModel):
    script: str = "pixcut-probe/print_via_app.sh"  # relative to project root (or absolute)
    dry_run: bool = False       # DEBUG: run the whole flow but never click 切割 (no print/ribbon), log success
    cutout: bool = False        # apply AI抠图 die-cut each print (consumes a trial credit)
    fresh: bool = True          # navigate Home->blank 4x7 canvas each print (more robust)
    margin_in: float = 0.0      # shrink the fitted image by this margin per side
    timeout_sec: float = 300.0  # a real print incl. job polling can take 1-2 min
    restart_every: int = 10     # restart Liene app every N prints to clear accumulated 画板 tabs (0 = never)


class PrintingCfg(BaseModel):
    enabled: bool = False
    printer_name: str = ""
    backend: str = "lp"         # "lp" = CUPS system printer | "pixcut" = Liene-app UI automation
    pixcut: PixcutCfg = Field(default_factory=PixcutCfg)


class StorageCfg(BaseModel):
    data_dir: str = "./data"
    history_retention_days: int = 3


class LoggingCfg(BaseModel):
    level: str = "INFO"
    max_bytes: int = 5_000_000  # rotate each log file at ~5 MB
    backup_count: int = 5       # keep this many rotations (~25 MB hard cap); oldest auto-deleted
    retention_days: int = 7     # also prune any *.log* older than this on startup (0 = off)


class Config(BaseModel):
    comfyui: ComfyuiCfg = Field(default_factory=ComfyuiCfg)
    generation: GenerationCfg = Field(default_factory=GenerationCfg)
    camera: CameraCfg = Field(default_factory=CameraCfg)
    recognition: RecognitionCfg = Field(default_factory=RecognitionCfg)
    orchestration: OrchestrationCfg = Field(default_factory=OrchestrationCfg)
    server: ServerCfg = Field(default_factory=ServerCfg)
    printing: PrintingCfg = Field(default_factory=PrintingCfg)
    storage: StorageCfg = Field(default_factory=StorageCfg)
    logging: LoggingCfg = Field(default_factory=LoggingCfg)

    @property
    def data_path(self) -> Path:
        return Path(self.storage.data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_path / "app.db"

    @property
    def enrolled_dir(self) -> Path:
        return self.data_path / "enrolled"

    @property
    def output_dir(self) -> Path:
        return self.data_path / "outputs"

    @property
    def log_dir(self) -> Path:
        return self.data_path / "logs"

    def ensure_dirs(self) -> None:
        for p in (self.data_path, self.enrolled_dir, self.output_dir, self.log_dir):
            p.mkdir(parents=True, exist_ok=True)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"


@lru_cache(maxsize=1)
def load_config(path: str | None = None) -> Config:
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return Config(**raw)
