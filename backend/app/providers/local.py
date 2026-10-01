"""Provider local (sem custo): movimento de câmera sobre imagem com ffmpeg (IMAGE + MOTION)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from .. import media
from .base import MediaResult, Usage

PROVIDER = "local"
MOTION_MODEL = "ffmpeg-kenburns"


class LocalMotion:
    name = PROVIDER

    def render(self, image: bytes, duration: float, motion: str, *, width: int = 1920, height: int = 1080,
               fps: int = 30) -> MediaResult:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "frame.jpg"
            out = Path(tmp) / "clip.mp4"
            src.write_bytes(media.fit_cover(image, width, height))
            media.render_motion(src, out, duration, motion, width=width, height=height, fps=fps)
            data = out.read_bytes()
        usage = Usage(provider=PROVIDER, model=MOTION_MODEL, operation="motion", units=round(duration, 2),
                      unit="seconds", cost_usd=0.0, cost_source="free")
        return MediaResult(data=data, mime="video/mp4", usage=usage,
                           meta={"params": {"motion": motion, "fps": fps, "size": f"{width}x{height}"}})
