"""Montagem do vídeo final com ffmpeg (sem IA e sem custo de API).

Cenas (movimento local, vídeo IA ou imagem) + transições entre cenas + texto na tela com efeito de
máquina de escrever + narração + efeitos sonoros sintetizados.

Como a montagem fica leve (também em ARM): cada cena vira um "corpo" e cada corte vira um pedaço
de transição; os pedaços são codificados um a um (MP4) e juntados sem recodificar. A linha do
tempo segue a narração: a cena i ocupa [início_i, início_i + duração do áudio_i]; a transição de
entrada da cena i acontece no começo dela, misturando o final estendido da cena anterior.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import sfx
from .config import get_settings
from .media import MediaError, ffmpeg, render_motion, video_duration

# nome na cena → (transição do ffmpeg xfade, duração em segundos)
TRANSITIONS: dict[str, tuple[str | None, float]] = {
    "dissolve": ("fade", 0.6),
    "fadeblack": ("fadeblack", 0.9),
    "flash": ("fadewhite", 0.4),
    "slide": ("smoothleft", 0.6),
    "zoom": ("zoomin", 0.6),
    "blur": ("hblur", 0.7),
    "circle": ("circleopen", 0.8),
    "cut": (None, 0.0),
}
LONG_SCENE = 12.0  # cenas mais longas ganham um segundo enquadramento (aproximação) no meio
PUNCH_IN = 1.22
TYPE_CPS = 17.0  # caracteres por segundo da máquina de escrever
FADE_IN, FADE_OUT = 0.8, 1.2
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

log = logging.getLogger("dark_model.montage")
ProgressFn = Callable[[float, str], None]
CancelFn = Callable[[], bool]


class Canceled(Exception):
    pass


def _short(exc: Exception) -> str:
    return str(exc).split(" | ")[-1][:160]


@dataclass
class Shot:
    duration: float  # duração da cena = duração da narração dela
    audio: Path
    kind: str = "motion"  # motion | video | still
    clip: Path | None = None  # movimento local (motion) ou vídeo IA (video)
    image: Path | None = None
    motion: str = "zoom_in"
    transition: str = "dissolve"  # entrada desta cena
    overlay: str = ""
    sfx: str = "none"


@dataclass
class Spec:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    crf: int = 21
    preset: str = "veryfast"
    font: Path | None = None
    warnings: list[str] = field(default_factory=list)


def find_font() -> Path | None:
    configured = get_settings().overlay_font
    for candidate in ([configured] if configured else []) + list(FONT_CANDIDATES):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    for root in (Path("/usr/share/fonts"), Path("/usr/local/share/fonts")):
        if root.is_dir():
            for p in sorted(root.rglob("*.ttf")):
                return p
    return None


# ------------------------------------------------------------------ linha do tempo


@dataclass
class Timeline:
    starts: list[float]
    trans: list[tuple[str | None, float]]  # transição de entrada de cada cena (a primeira não tem)
    total: float


def timeline(shots: list[Shot]) -> Timeline:
    starts, t = [], 0.0
    for s in shots:
        starts.append(t)
        t += s.duration
    trans: list[tuple[str | None, float]] = [(None, 0.0)]
    for prev, cur in zip(shots, shots[1:]):
        name, d = TRANSITIONS.get(cur.transition, TRANSITIONS["dissolve"])
        d = min(d, prev.duration / 3, cur.duration / 3)
        trans.append((name, d) if name and d >= 0.15 else (None, 0.0))
    return Timeline(starts, trans, t)


def _frame(t: float, fps: int) -> int:
    return int(round(t * fps))


# ------------------------------------------------------------------ fontes de vídeo de cada cena


@dataclass
class Source:
    path: Path
    still: bool  # imagem parada (loop)
    length: float  # duração disponível (inf para imagem)


def _norm(spec: Spec) -> str:
    return (f"fps={spec.fps},scale={spec.width}:{spec.height}:force_original_aspect_ratio=increase,"
            f"crop={spec.width}:{spec.height},setsar=1,format=yuv420p")


def _restart(spec: Spec) -> str:
    """Zera o tempo e declara taxa de quadros constante (o xfade do ffmpeg 7 recusa taxa desconhecida)."""
    return f"setpts=PTS-STARTPTS,fps={spec.fps}"


def _last_frame(clip: Path, out: Path) -> Path:
    # decodifica só o vídeo e fica com o último quadro (funciona mesmo se o áudio do clipe for mais longo)
    ffmpeg("-i", str(clip), "-map", "0:v:0", "-update", "1", "-q:v", "2", str(out), timeout=300)
    return out


def prepare_source(i: int, shot: Shot, need: float, spec: Spec, work: Path,
                   report: Callable[[float, str], None] | None = None) -> Source:
    """Vídeo da cena com pelo menos `need` segundos (cena + sobra para a transição seguinte).

    Na maioria das cenas o clipe já existe e nada é feito aqui; `report(fração, o que está fazendo)`
    informa o andamento quando é preciso gerar movimento (etapa mais pesada da montagem).
    """
    def step(what: str, a: float, b: float):
        return (lambda f: report(a + (b - a) * f, what)) if report else None

    if shot.kind == "still" and shot.image:
        return Source(shot.image, True, math.inf)
    if shot.kind == "video" and shot.clip:
        length = video_duration(shot.clip)
        if length + 0.05 >= need:
            return Source(shot.clip, False, length)
        if length > 0.5:
            # vídeo IA mais curto que a narração: continua com movimento suave sobre o último quadro
            what = f"completando o vídeo IA com movimento ({need - length:.0f} s)"
            log.info("montagem: cena %s — %s", i + 1, what)
            last = _last_frame(shot.clip, work / f"last_{i:04d}.jpg")
            tail = work / f"tail_{i:04d}.mp4"
            render_motion(last, tail, need - length + 0.6, shot.motion if shot.motion != "static" else "zoom_in",
                          width=spec.width, height=spec.height, fps=spec.fps, progress=step(what, 0.0, 0.6))
            joined = work / f"src_{i:04d}.mp4"
            off = max(0.1, length - 0.5)
            graph = (f"[0:v]{_norm(spec)},{_restart(spec)}[a];[1:v]{_norm(spec)},{_restart(spec)}[b];"
                     f"[a][b]xfade=transition=fade:duration=0.5:offset={off:.3f}[v]")
            ffmpeg("-i", str(shot.clip), "-i", str(tail), "-filter_complex", graph, "-map", "[v]", "-an",
                   "-c:v", "libx264", "-preset", spec.preset, "-crf", str(spec.crf - 2), str(joined), timeout=1800,
                   progress=step(what, 0.6, 1.0), duration=need)
            return Source(joined, False, video_duration(joined) or need)
    if shot.kind == "motion" and shot.clip:
        length = video_duration(shot.clip)
        # clipe bem mais curto que a narração (ex.: áudio refeito): gera o movimento de novo a partir da imagem
        if length + 0.5 >= shot.duration or not shot.image:
            return Source(shot.clip, False, length)
    if shot.image:
        # sem clipe pronto: movimento gerado agora a partir da imagem
        what = f"gerando o movimento da imagem ({need:.0f} s)"
        log.info("montagem: cena %s — %s", i + 1, what)
        out = work / f"src_{i:04d}.mp4"
        render_motion(shot.image, out, need + 0.2, shot.motion if shot.motion != "static" else "zoom_in",
                      width=spec.width, height=spec.height, fps=spec.fps, progress=step(what, 0.0, 1.0))
        return Source(out, False, video_duration(out) or need)
    raise MediaError(f"cena {i + 1} sem imagem nem vídeo")


def _input(src: Source, start: float, length: float, work: Path, tag: str) -> list[str]:
    """Argumentos de entrada do ffmpeg para `length` segundos da fonte a partir de `start`."""
    if src.still:
        return ["-loop", "1", "-framerate", "30", "-t", f"{length + 1:.3f}", "-i", str(src.path)]
    if start >= src.length - 0.06:
        # pedido além do fim do clipe (sobra da transição): congela o último quadro
        last = work / f"freeze_{tag}.jpg"
        if not last.exists():
            _last_frame(src.path, last)
        return ["-loop", "1", "-framerate", "30", "-t", f"{length + 1:.3f}", "-i", str(last)]
    return ["-ss", f"{start:.3f}", "-t", f"{length + 1:.3f}", "-i", str(src.path)]


# ------------------------------------------------------------------ texto na tela


def _text_filters(text: str, length: float, spec: Spec, work: Path, tag: str) -> tuple[list[str], tuple[float, float, int]]:
    """drawtext revelando o texto letra a letra; devolve (filtros, (início, segundos por letra, letras))."""
    text = " ".join(text.split())
    if not text or spec.font is None or length < 1.8:
        return [], (0.0, 0.0, 0)
    t0 = 0.35
    n = len(text)
    dt = min(1.0 / TYPE_CPS, (length * 0.45) / n)
    end = max(t0 + n * dt + 1.2, length - 0.45)
    s = spec.height / 1080
    fs, pad = round(46 * s), round(18 * s)
    common = (f"fontfile='{spec.font}':fontsize={fs}:fontcolor=0xF3EBDC:box=1:boxcolor=0x0B0A08@0.62:"
              f"boxborderw={pad}:x={round(spec.width * 0.06)}:y=h-{round(190 * s)}:expansion=none:fix_bounds=1")
    filters = []
    for k in range(1, n):
        if text[k - 1] == " ":
            continue  # o espaço aparece junto com a próxima letra
        f = work / f"txt_{tag}_{k:03d}.txt"
        f.write_text(text[:k] + "_", encoding="utf-8")
        a, b = t0 + (k - 1) * dt, t0 + k * dt
        # o prefixo k fica na tela até a próxima letra visível
        j = k + 1
        while j < n and text[j - 1] == " ":
            j += 1
        b = t0 + (j - 1) * dt
        filters.append(f"drawtext=textfile='{f}':{common}:enable='gte(t,{a:.3f})*lt(t,{b:.3f})'")
    full = work / f"txt_{tag}_full.txt"
    full.write_text(text, encoding="utf-8")
    a = t0 + (n - 1) * dt
    filters.append(f"drawtext=textfile='{full}':{common}:enable='gte(t,{a:.3f})':"
                   f"alpha='if(lt(t,{end:.3f}),1,max(0,1-(t-{end:.3f})/0.4))'")
    return filters, (t0, dt, n)


# ------------------------------------------------------------------ pedaços


def _encode(inputs: list[str], graph: str, frames: int, out: Path, spec: Spec, work: Path,
            progress: Callable[[float], None] | None = None) -> None:
    ffmpeg(*inputs, "-filter_complex", graph, "-map", "[v]", "-an", "-frames:v", str(frames),
           "-c:v", "libx264", "-preset", spec.preset, "-crf", str(spec.crf), "-pix_fmt", "yuv420p",
           "-r", str(spec.fps), "-g", str(spec.fps * 4), "-video_track_timescale", str(spec.fps * 1000),
           "-f", "mp4", str(out), timeout=1800, progress=progress, duration=frames / spec.fps)


def _body(i: int, n: int, src: Source, shot: Shot, a: float, length: float, frames: int, spec: Spec,
          work: Path, simple: bool = False,
          progress: Callable[[float], None] | None = None) -> tuple[Path, tuple[float, float, int]]:
    out = work / f"p_{i:04d}_b.mp4"
    pad = f"tpad=stop_mode=clone:stop_duration={length + 1:.3f},{_restart(spec)}"
    chain = [f"[0:v]{_norm(spec)},{pad}[base]"]
    last = "base"
    if simple:
        chain.append("[base]null[v]")
        _encode(_input(src, a, length, work, f"{i:04d}"), ";".join(chain), frames, out, spec, work, progress)
        return out, (0.0, 0.0, 0)
    if length > LONG_SCENE and shot.kind != "video":
        # segundo enquadramento: aproxima numa região da imagem no meio da cena (sem gerar imagem nova)
        cut, xf = length / 2, 0.5
        fx = (0.5, 0.18, 0.82)[i % 3]
        chain.append(f"[{last}]split=2[p][q]")
        chain.append(f"[p]trim=end={cut + xf:.3f},{_restart(spec)}[p1]")
        chain.append(f"[q]trim=start={cut:.3f},{_restart(spec)},crop=w=iw/{PUNCH_IN}:h=ih/{PUNCH_IN}:"
                     f"x=(iw-ow)*{fx}:y=(ih-oh)*0.42,scale={spec.width}:{spec.height},setsar=1[q1]")
        chain.append(f"[p1][q1]xfade=transition=fade:duration={xf}:offset={cut:.3f}[punch]")
        last = "punch"
    filters, typing = _text_filters(shot.overlay, length, spec, work, f"{i:04d}")
    if i == 0:
        filters.append(f"fade=t=in:st=0:d={min(FADE_IN, length / 3):.3f}")
    if i == n - 1:
        d = min(FADE_OUT, length / 3)
        filters.append(f"fade=t=out:st={max(0.0, length - d):.3f}:d={d:.3f}")
    chain.append(f"[{last}]{','.join(filters) if filters else 'null'}[v]")
    _encode(_input(src, a, length, work, f"{i:04d}"), ";".join(chain), frames, out, spec, work, progress)
    return out, typing


def _transition(i: int, prev: Source, prev_at: float, cur: Source, name: str | None, d: float, frames: int, spec: Spec,
                work: Path) -> Path:
    out = work / f"p_{i:04d}_t.mp4"
    pad = f"tpad=stop_mode=clone:stop_duration={d + 1:.3f},{_restart(spec)}"
    if name is None:
        # alternativa sem efeito: o começo da cena atual
        _encode(_input(cur, 0.0, d, work, f"{i:04d}"), f"[0:v]{_norm(spec)},{pad}[v]", frames, out, spec, work)
        return out
    graph = (f"[0:v]{_norm(spec)},{pad}[a];[1:v]{_norm(spec)},{pad}[b];"
             f"[a][b]xfade=transition={name}:duration={d:.3f}:offset=0[v]")
    inputs = _input(prev, prev_at, d, work, f"{i - 1:04d}") + _input(cur, 0.0, d, work, f"{i:04d}")
    _encode(inputs, graph, frames, out, spec, work)
    return out


# ------------------------------------------------------------------ áudio


def _audio(shots: list[Shot], tl: Timeline, typing: list[tuple[int, float, float, int]], out: Path,
           work: Path) -> None:
    inputs: list[str] = []
    graph: list[str] = []
    for k, s in enumerate(shots):
        inputs += ["-i", str(s.audio)]
        # cada narração com a duração exata da cena: sem atraso acumulado entre áudio e imagem
        graph.append(f"[{k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=mono,"
                     f"apad,atrim=0:{s.duration:.4f},asetpts=PTS-STARTPTS[n{k}]")
    graph.append("".join(f"[n{k}]" for k in range(len(shots))) + f"concat=n={len(shots)}:v=0:a=1[narr]")
    events: list[str] = []
    cache: dict[str, Path] = {}
    idx = len(shots)
    for k, s in enumerate(shots):
        if s.sfx in sfx.EFFECTS:
            effect = sfx.EFFECTS[s.sfx]
            if s.sfx not in cache:
                cache[s.sfx] = work / f"sfx_{s.sfx}.wav"
                sfx.render(s.sfx, cache[s.sfx])
            start = max(0.0, tl.starts[k] + effect.offset)
            length = effect.seconds
            if effect.ambient:
                length = max(1.0, min(effect.seconds, s.duration - 0.2))
            fade = min(0.8, length / 3)
            inputs += ["-i", str(cache[s.sfx])]
            graph.append(f"[{idx}:a]atrim=0:{length:.3f},afade=t=out:st={length - fade:.3f}:d={fade:.3f},"
                         f"volume={effect.volume},adelay={int(start * 1000)}:all=1[e{idx}]")
            events.append(f"[e{idx}]")
            idx += 1
    for k, t0, dt, chars in typing:
        if not chars:
            continue
        clicks = work / f"typing_{k:04d}.wav"
        sfx.render_typing(chars, dt, clicks)
        start = tl.starts[k] + tl.trans[k][1] + t0
        inputs += ["-i", str(clicks)]
        graph.append(f"[{idx}:a]volume={sfx.TYPING_VOLUME},adelay={int(start * 1000)}:all=1[e{idx}]")
        events.append(f"[e{idx}]")
        idx += 1
    if events:
        graph.append(f"[narr]{''.join(events)}amix=inputs={len(events) + 1}:duration=first:dropout_transition=0:"
                     "normalize=0,alimiter=limit=0.95[mix]")
    else:
        graph.append("[narr]anull[mix]")
    graph.append("[mix]aformat=sample_fmts=s16:channel_layouts=stereo[a]")
    ffmpeg(*inputs, "-filter_complex", ";".join(graph), "-map", "[a]", "-ar", "48000", str(out), timeout=1800)


# ------------------------------------------------------------------ montagem


def build(shots: list[Shot], out: Path, spec: Spec, work: Path, *, progress: ProgressFn | None = None,
          canceled: CancelFn | None = None) -> dict:
    if not shots:
        raise MediaError("nenhuma cena para montar")
    work.mkdir(parents=True, exist_ok=True)
    tl = timeline(shots)
    fps = spec.fps
    n = len(shots)

    def tick(done: float, msg: str) -> None:
        if canceled and canceled():
            raise Canceled()
        if progress:
            progress(done, msg)

    started = time.monotonic()
    log.info("montagem: %s cenas, %.1f min, %sx%s@%s", n, tl.total / 60, spec.width, spec.height, fps)
    sources: list[Source] = []
    for i, s in enumerate(shots):
        tick(0.02 + 0.13 * i / n, f"preparando cena {i + 1}/{n}")
        need = s.duration + (tl.trans[i + 1][1] if i + 1 < n else 0.0)

        def report(f: float, what: str, i: int = i) -> None:
            tick(0.02 + 0.13 * (i + f) / n, f"preparando cena {i + 1}/{n}: {what} {f * 100:.0f}%")

        t0 = time.monotonic()
        try:
            sources.append(prepare_source(i, s, need, spec, work, report))
        except MediaError as exc:
            if not s.image:
                raise
            spec.warnings.append(f"cena {i + 1}: clipe com problema, usada a imagem parada ({_short(exc)})")
            sources.append(Source(s.image, True, math.inf))
        if time.monotonic() - t0 > 5:
            log.info("montagem: cena %s preparada em %.0f s", i + 1, time.monotonic() - t0)
    log.info("montagem: cenas preparadas em %.0f s", time.monotonic() - started)

    pieces: list[Path] = []
    typing: list[tuple[int, float, float, int]] = []
    total_frames = max(1, _frame(tl.total, fps))
    phase = time.monotonic()

    def piece_tick(at_frame: float, i: int) -> None:
        f = min(1.0, at_frame / total_frames)
        elapsed = time.monotonic() - phase
        eta = ""
        if f > 0.03 and elapsed > 10:
            left = elapsed / f * (1 - f)
            eta = f" · faltam ~{max(1, round(left / 60))} min" if left >= 60 else f" · faltam ~{max(5, round(left))} s"
        tick(0.15 + 0.72 * f, f"montando cena {i + 1}/{n}{eta}")

    for i, s in enumerate(shots):
        start_frame = _frame(tl.starts[i], fps)
        piece_tick(start_frame, i)
        name, d = tl.trans[i]
        if i > 0 and name:
            frames = _frame(tl.starts[i] + d, fps) - _frame(tl.starts[i], fps)
            if frames > 0:
                try:
                    piece = _transition(i, sources[i - 1], shots[i - 1].duration, sources[i], name, d, frames,
                                        spec, work)
                except MediaError as exc:
                    spec.warnings.append(f"cena {i + 1}: transição trocada por corte ({_short(exc)})")
                    piece = _transition(i, sources[i - 1], shots[i - 1].duration, sources[i], None, d, frames,
                                        spec, work)
                pieces.append(piece)
        body_start = tl.starts[i] + (d if name else 0.0)
        body_end = tl.starts[i] + s.duration
        frames = _frame(body_end, fps) - _frame(body_start, fps)
        if frames > 0:
            args = (i, n, sources[i], s, d if name else 0.0, body_end - body_start, frames, spec, work)
            first = _frame(body_start, fps)

            def body_progress(f: float, i: int = i, first: int = first, frames: int = frames) -> None:
                piece_tick(first + f * frames, i)

            try:
                piece, (t0, dt, chars) = _body(*args, progress=body_progress)
            except MediaError as exc:
                spec.warnings.append(f"cena {i + 1}: sem texto/efeito visual ({_short(exc)})")
                log.warning("montagem: cena %s refeita sem texto/efeito: %s", i + 1, _short(exc))
                piece, (t0, dt, chars) = _body(*args, simple=True, progress=body_progress)
            pieces.append(piece)
            typing.append((i, t0, dt, chars))

    log.info("montagem: cenas codificadas em %.0f s", time.monotonic() - phase)
    tick(0.87, "mixando narração e efeitos sonoros")
    audio = work / "mix.wav"
    _audio(shots, tl, typing, audio, work)

    tick(0.94, "juntando vídeo e áudio")
    listing = work / "pieces.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in pieces), encoding="utf-8")
    ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(audio), "-map", "0:v", "-map", "1:a",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(out),
           timeout=3600)
    log.info("montagem concluída em %.0f s (%s avisos)", time.monotonic() - started, len(spec.warnings))
    return {"duration": tl.total, "pieces": len(pieces), "scenes": n,
            "transitions": sum(1 for name, _ in tl.trans if name), "overlays": sum(1 for *_, c in typing if c),
            "sfx": sum(1 for s in shots if s.sfx in sfx.EFFECTS), "warnings": spec.warnings}
