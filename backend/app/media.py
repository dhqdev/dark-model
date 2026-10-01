"""Utilidades de mídia: ffmpeg/ffprobe e tratamento de imagens (Pillow)."""

from __future__ import annotations

import base64
import io
import json
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from .config import get_settings

MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "static")


class MediaError(Exception):
    pass


def run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess[bytes]:
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:  # pragma: no cover - depende do ambiente
        raise MediaError(f"executável não encontrado: {args[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{Path(args[0]).name} excedeu {timeout}s") from exc
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace").strip().splitlines()[-6:]
        raise MediaError(f"{Path(args[0]).name} falhou: " + " | ".join(tail))
    return proc


def ffmpeg(*args: str, timeout: int = 900) -> None:
    run([get_settings().ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", *args], timeout=timeout)


def _probe_with_ffmpeg(path: Path) -> dict:
    """Alternativa quando só existe o ffmpeg (sem ffprobe): lê a saída de `ffmpeg -i`."""
    proc = subprocess.run([get_settings().ffmpeg_bin, "-hide_banner", "-i", str(path)], capture_output=True, timeout=60)
    err = proc.stderr.decode(errors="replace")
    info: dict = {"duration": None, "width": None, "height": None}
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    v = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err)
    if v:
        info["width"], info["height"] = int(v.group(1)), int(v.group(2))
    return info


def probe(path: Path) -> dict:
    try:
        proc = run(
            [
                get_settings().ffprobe_bin, "-v", "error", "-print_format", "json",
                "-show_entries", "format=duration:stream=codec_type,width,height,duration",
                str(path),
            ],
            timeout=60,
        )
    except MediaError as exc:
        if "não encontrado" in str(exc):
            return _probe_with_ffmpeg(path)
        raise
    data = json.loads(proc.stdout or b"{}")
    info: dict = {"duration": None, "width": None, "height": None}
    fmt = data.get("format") or {}
    if fmt.get("duration") not in (None, "N/A"):
        info["duration"] = float(fmt["duration"])
    for st in data.get("streams") or []:
        if st.get("codec_type") == "video":
            info["width"] = st.get("width")
            info["height"] = st.get("height")
            if info["duration"] is None and st.get("duration") not in (None, "N/A"):
                info["duration"] = float(st["duration"])
    return info


def probe_duration(path: Path) -> float | None:
    return probe(path).get("duration")


def video_duration(path: Path) -> float:
    """Duração da trilha de vídeo (um clipe de IA pode ter áudio mais longo que a imagem)."""
    try:
        proc = run([get_settings().ffprobe_bin, "-v", "error", "-select_streams", "v:0", "-show_entries",
                    "stream=duration", "-of", "default=nw=1:nk=1", str(path)], timeout=60)
        value = proc.stdout.decode().strip().splitlines()
        if value and value[0] not in ("", "N/A"):
            return float(value[0])
    except (MediaError, ValueError):
        pass
    return float(probe(path).get("duration") or 0.0)


# ---------------------------------------------------------------- imagens


def image_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def fit_cover(data: bytes, width: int, height: int, *, fmt: str = "JPEG", quality: int = 92) -> bytes:
    """Redimensiona e recorta pelo centro para preencher exatamente width×height."""
    with Image.open(io.BytesIO(data)) as im:
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            background = Image.new("RGB", im.size, (0, 0, 0))
            rgba = im.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            im = background
        else:
            im = im.convert("RGB")
        out = ImageOps.fit(im, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        buf = io.BytesIO()
        if fmt.upper() == "JPEG":
            out.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
        else:
            out.save(buf, fmt.upper(), optimize=True)
        return buf.getvalue()


def jpeg_data_url(data: bytes, max_side: int = 1536, quality: int = 88) -> str:
    """Imagem como data URL JPEG (para enviar como quadro inicial de vídeo / referência)."""
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------- movimento (Ken Burns)


def _motion_exprs(motion: str, frames: int) -> tuple[str, str, str]:
    n = max(frames - 1, 1)
    # progresso 0→1 com suavização (smoothstep)
    t = f"min(on/{n}\\,1)"
    e = f"({t}*{t}*(3-2*{t}))"
    zoom = 1.15
    pan_zoom = 1.12
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"
    if motion == "zoom_in":
        return f"1+{zoom - 1:.3f}*{e}", cx, cy
    if motion == "zoom_out":
        return f"{zoom:.3f}-{zoom - 1:.3f}*{e}", cx, cy
    if motion == "pan_right":
        return f"{pan_zoom}", f"(iw-iw/zoom)*{e}", cy
    if motion == "pan_left":
        return f"{pan_zoom}", f"(iw-iw/zoom)*(1-{e})", cy
    if motion == "pan_down":
        return f"{pan_zoom}", cx, f"(ih-ih/zoom)*{e}"
    if motion == "pan_up":
        return f"{pan_zoom}", cx, f"(ih-ih/zoom)*(1-{e})"
    return "1", "0", "0"


def render_motion(
    image_path: Path,
    out_path: Path,
    duration: float,
    motion: str = "zoom_in",
    *,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> None:
    """Gera um clipe MP4 a partir de uma imagem com movimento de câmera (zoom/pan)."""
    duration = max(1.0, float(duration))
    frames = max(2, round(duration * fps))
    z, x, y = _motion_exprs(motion if motion in MOTIONS else "zoom_in", frames)
    # entrada ampliada 2x reduz o "tremido" do zoompan (que arredonda x/y para inteiros)
    big_w, big_h = width * 2, height * 2
    vf = (
        f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,crop={big_w}:{big_h},"
        f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
        "format=yuv420p"
    )
    ffmpeg(
        "-i", str(image_path), "-vf", vf, "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart",
        str(out_path),
        timeout=1800,
    )


# ---------------------------------------------------------------- áudio


def to_mp3(data: bytes, content_type: str) -> bytes:
    """Converte a resposta do TTS para MP3 quando o provider devolve outro formato."""
    ct = (content_type or "").lower()
    if "mpeg" in ct or "mp3" in ct:
        return data
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.bin"
        dst = Path(tmp) / "out.mp3"
        src.write_bytes(data)
        if "pcm" in ct or "l16" in ct or "raw" in ct:
            rate = "24000"
            for part in ct.split(";"):
                if "rate=" in part:
                    rate = part.split("=", 1)[1].strip()
            ffmpeg("-f", "s16le", "-ar", rate, "-ac", "1", "-i", str(src), "-c:a", "libmp3lame", "-b:a", "192k", str(dst))
        else:
            ffmpeg("-i", str(src), "-c:a", "libmp3lame", "-b:a", "192k", str(dst))
        return dst.read_bytes()


def concat_audio(paths: list[Path], out_path: Path, gap_seconds: float = 0.0) -> None:
    """Junta os áudios das cenas (reencodando para evitar problemas de formato)."""
    if not paths:
        raise MediaError("nenhum áudio para juntar")
    inputs: list[str] = []
    filters: list[str] = []
    labels: list[str] = []
    for i, p in enumerate(paths):
        inputs += ["-i", str(p)]
        filters.append(f"[{i}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=mono[a{i}]")
        labels.append(f"[a{i}]")
        if gap_seconds > 0 and i < len(paths) - 1:
            filters.append(
                f"anullsrc=r=44100:cl=mono,atrim=duration={gap_seconds:.3f},aformat=sample_fmts=fltp[g{i}]"
            )
            labels.append(f"[g{i}]")
    graph = ";".join(filters) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=0:a=1[out]"
    ffmpeg(*inputs, "-filter_complex", graph, "-map", "[out]", "-c:a", "libmp3lame", "-b:a", "192k", str(out_path),
           timeout=1800)


def silence_mp3(seconds: float, out_path: Path) -> None:
    ffmpeg("-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono", "-t", f"{max(seconds, 0.1):.3f}",
           "-c:a", "libmp3lame", "-b:a", "128k", str(out_path))
