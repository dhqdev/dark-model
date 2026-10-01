"""Efeitos sonoros sintetizados localmente com o ffmpeg (sem custo e sem direitos autorais de terceiros).

Cada efeito é uma receita de síntese (ruído filtrado, senoides com envelope). A IA escolhe o efeito
de algumas cenas; o tempo de cada um no vídeo é decidido pela montagem.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .media import ffmpeg

RATE = 48000


@dataclass(frozen=True)
class Effect:
    label: str
    # fonte de áudio (lavfi) + filtros; {d} = duração em segundos
    source: str
    filters: str
    seconds: float
    volume: float
    # onde começa em relação ao início da cena (negativo = antes do corte)
    offset: float = 0.0
    # efeitos de ambiente acompanham a cena (cortados na duração dela)
    ambient: bool = False


EFFECTS: dict[str, Effect] = {
    "whoosh": Effect(
        "Whoosh", "anoisesrc=d={d}:c=pink:r=48000:a=0.6",
        "highpass=f=350,lowpass=f=5500,flanger=delay=3:depth=6:speed=1.2,"
        "afade=t=in:d=0.5:curve=qsin,afade=t=out:st=0.5:d=0.6:curve=qsin,volume=4", 1.1, 0.5, offset=-0.45),
    "impact": Effect(
        "Impacto",
        "aevalsrc='0.85*sin(2*PI*(52*t-14*t*t))*exp(-2.6*t)+0.35*(2*random(0)-1)*exp(-22*t)':s=48000:d={d}",
        "lowpass=f=2500,afade=t=out:st=1.6:d=0.6", 2.2, 0.65),
    "riser": Effect(
        "Subida",
        "aevalsrc='0.32*sin(2*PI*(160*t+60*t*t*t))*pow(t/{d},2)+0.14*(2*random(0)-1)*pow(t/{d},3)':s=48000:d={d}",
        "highpass=f=120,afade=t=out:st=2.35:d=0.15", 2.5, 0.45, offset=-2.5),
    "tension": Effect(
        "Tensão",
        "aevalsrc='0.22*sin(2*PI*55*t)*(0.7+0.3*sin(2*PI*0.45*t))+0.12*sin(2*PI*82.4*t)+0.05*sin(2*PI*110.6*t)':s=48000:d={d}",
        "lowpass=f=400,afade=t=in:d=1.5", 7.0, 0.5, offset=0.1, ambient=True),
    "heartbeat": Effect(
        "Batimento",
        "aevalsrc='0.9*sin(2*PI*48*mod(t,0.95))*exp(-14*mod(t,0.95))"
        "+0.6*gt(mod(t,0.95),0.28)*sin(2*PI*44*(mod(t,0.95)-0.28))*exp(-16*(mod(t,0.95)-0.28))':s=48000:d={d}",
        "lowpass=f=220", 3.8, 0.6, offset=0.05),
    "wind": Effect(
        "Vento", "anoisesrc=d={d}:c=brown:r=48000:a=0.7",
        "lowpass=f=650,highpass=f=60,tremolo=f=0.3:d=0.6,afade=t=in:d=1.5", 7.0, 0.4, offset=0.0, ambient=True),
    "rumble": Effect(
        "Estrondo grave",
        "aevalsrc='0.5*sin(2*PI*38*t)*(0.8+0.2*sin(2*PI*3*t))+0.4*(2*random(0)-1)':s=48000:d={d}",
        "lowpass=f=160,afade=t=in:d=0.6", 4.5, 0.55, offset=0.0, ambient=True),
    "clock": Effect(
        "Relógio",
        "aevalsrc='0.7*(2*random(0)-1)*exp(-150*mod(t,0.5))*lt(mod(t,0.5),0.04)*(1-0.35*gte(mod(t,1),0.5))':s=48000:d={d}",
        "highpass=f=1800", 4.0, 0.35, offset=0.1, ambient=True),
}

# cliques de máquina de escrever para o texto na tela
TYPING_VOLUME = 0.22


def render(name: str, out: Path, seconds: float | None = None) -> Effect:
    """Grava o efeito em WAV mono 48 kHz."""
    effect = EFFECTS[name]
    d = round(float(seconds or effect.seconds), 3)
    src = effect.source.replace("{d}", f"{d}")
    filters = effect.filters
    ffmpeg("-f", "lavfi", "-i", src, "-af", f"{filters},aformat=sample_fmts=s16:channel_layouts=mono",
           "-t", f"{d}", "-ar", str(RATE), "-ac", "1", str(out), timeout=120)
    return effect


def render_typing(chars: int, char_seconds: float, out: Path) -> None:
    """Cliques de teclas, um por caractere digitado."""
    d = max(0.2, chars * char_seconds)
    dt = char_seconds
    src = (f"aevalsrc='0.8*(2*random(0)-1)*exp(-420*mod(t,{dt:.4f}))*(0.6+0.4*random(1))':s={RATE}:d={d:.3f}")
    ffmpeg("-f", "lavfi", "-i", src, "-af", "highpass=f=1400,lowpass=f=7000,aformat=sample_fmts=s16:channel_layouts=mono",
           "-ar", str(RATE), "-ac", "1", str(out), timeout=120)
