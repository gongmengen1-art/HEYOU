"""Pluggable image-generation backend interface + factory."""
from __future__ import annotations

from typing import Protocol


class ImageGenBackend(Protocol):
    name: str

    def generate(self, portrait_path: str, seed: int, style_params: dict) -> bytes:
        """Take an enrolled portrait, return PNG/JPEG bytes of the generated 2D cartoon."""
        ...


def create_backend(cfg):
    backend = cfg.generation.backend.lower()
    if backend == "runninghub":
        from .runninghub import RunningHubBackend

        return RunningHubBackend(cfg)
    if backend == "mock":
        from .mock import MockBackend

        return MockBackend(cfg)
    raise ValueError(f"unknown generation backend: {cfg.generation.backend!r}")
