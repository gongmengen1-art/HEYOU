"""Centralized logging: size-rotating file logs in data/logs + stderr, self-cleaning.

Both entrypoints (web server, recognition loop) call ``setup_logging(cfg)`` once at
startup. File logs rotate by size so a long-running kiosk never fills the disk
(``max_bytes`` × ``backup_count`` is a hard cap — the oldest rotation is auto-deleted),
and any stale rotated/older log files left over from prior runs are pruned by age on
startup. Tune via the ``logging:`` block in config.yaml (see LoggingCfg)."""
from __future__ import annotations

import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import Config

LOG_FILENAME = "heyou.log"
_FMT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_configured = False


def prune_old_logs(log_dir, retention_days: int) -> int:
    """Delete ``*.log*`` files in *log_dir* older than *retention_days* (by mtime).

    Returns the number removed. ``retention_days <= 0`` disables pruning. This is a
    backstop for leftovers (rotation already caps the live files); it never touches
    non-log files."""
    log_dir = Path(log_dir)
    if retention_days <= 0 or not log_dir.is_dir():
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    for p in log_dir.glob("*.log*"):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def setup_logging(cfg: Config) -> None:
    """Idempotently attach a size-rotating file handler (data/logs/heyou.log) plus a
    stderr handler to the root logger. Safe to call from multiple entrypoints; only the
    first call configures handlers."""
    global _configured
    if _configured:
        return
    cfg.ensure_dirs()
    lc = cfg.logging
    log_path = cfg.log_dir / LOG_FILENAME

    # prune leftovers from prior runs before opening the new handler
    pruned = prune_old_logs(cfg.log_dir, lc.retention_days)

    level = getattr(logging, str(lc.level).upper(), logging.INFO)
    fmt = logging.Formatter(_FMT)

    file_h = RotatingFileHandler(
        log_path, maxBytes=lc.max_bytes, backupCount=lc.backup_count, encoding="utf-8"
    )
    file_h.setFormatter(fmt)
    file_h.setLevel(level)

    stream_h = logging.StreamHandler()
    stream_h.setFormatter(fmt)
    stream_h.setLevel(level)

    root = logging.getLogger()
    root.setLevel(level)
    # drop any pre-existing handlers (e.g. a stray basicConfig) so lines aren't duplicated
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(file_h)
    root.addHandler(stream_h)

    _configured = True
    logging.getLogger("heyou").info(
        "logging → %s (rotate %d bytes ×%d backups, prune >%dd; pruned %d stale)",
        log_path, lc.max_bytes, lc.backup_count, lc.retention_days, pruned,
    )
