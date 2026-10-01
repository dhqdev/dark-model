"""Texto: divisão em frases, métricas do roteiro, repetição, duração e legendas (SRT)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

# palavras por minuto de narração (média de narradores de documentário)
LANG_WPM = {
    "en": 150, "pt": 150, "es": 160, "fr": 150, "it": 150, "de": 135, "pl": 130, "nl": 145, "ru": 130,
    "uk": 130, "cs": 130, "sk": 130, "ro": 140, "tr": 135, "sv": 145, "no": 145, "da": 145, "fi": 120,
    "hu": 125, "el": 135, "id": 140, "vi": 150, "hi": 140, "ar": 130, "ja": 280, "ko": 260, "zh": 200,
}

LANGUAGE_NAMES = {
    "en": "English", "pt": "Portuguese", "es": "Spanish", "fr": "French", "it": "Italian", "de": "German",
    "pl": "Polish", "nl": "Dutch", "ru": "Russian", "uk": "Ukrainian", "cs": "Czech", "sk": "Slovak",
    "ro": "Romanian", "tr": "Turkish", "sv": "Swedish", "no": "Norwegian", "da": "Danish", "fi": "Finnish",
    "hu": "Hungarian", "el": "Greek", "id": "Indonesian", "vi": "Vietnamese", "hi": "Hindi", "ar": "Arabic",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese",
}

_ABBREVIATIONS = {
    # en
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "approx.", "no.",
    "inc.", "ltd.", "co.", "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.", "sep.", "sept.", "oct.",
    "nov.", "dec.", "u.s.", "u.k.", "a.m.", "p.m.",
    # pt/es
    "sra.", "srta.", "dra.", "p.ex.", "ex.", "pág.", "núm.", "art.", "av.", "cap.", "séc.", "a.c.", "d.c.",
    # de
    "z.b.", "bzw.", "usw.", "ca.", "evtl.", "ggf.", "inkl.", "nr.", "str.", "d.h.", "u.a.", "v.chr.", "n.chr.",
    # pl
    "np.", "itd.", "itp.", "tzw.", "ok.", "m.in.", "r.", "w.", "tj.", "ul.", "godz.", "wg.", "pt.", "zob.",
}

_END = re.compile(r"([.!?…]+[\"'”’»)\]]*)(\s+)")
_WORD = re.compile(r"[\w’'-]+", re.UNICODE)


@dataclass
class Segment:
    index: int
    text: str
    paragraph: int
    words: int


def lang_base(code: str | None) -> str:
    return (code or "en").split("-")[0].split("_")[0].lower()


def language_label(code: str | None) -> str:
    base = lang_base(code)
    return f"{LANGUAGE_NAMES.get(base, base)} ({code})"


def default_wpm(code: str | None) -> int:
    return LANG_WPM.get(lang_base(code), 145)


def words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def word_count(text: str) -> int:
    return len(words(text))


def estimate_seconds(text: str, wpm: int) -> float:
    return round(word_count(text) / max(wpm, 60) * 60.0, 2)


def content_hash(*parts: object) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode())
        h.update(b"\x1f")
    return h.hexdigest()[:32]


def split_sentences(paragraph: str) -> list[str]:
    text = re.sub(r"\s+", " ", paragraph).strip()
    if not text:
        return []
    out: list[str] = []
    start = 0
    for m in _END.finditer(text):
        end = m.end(1)
        following = text[m.end():m.end() + 3]
        first = following.lstrip("\"'“«‘([—–- ")[:1]
        if not first or not (first.isupper() or first.isdigit()):
            continue
        tail = re.search(r"(\S+)$", text[start:end])
        token = tail.group(1).lower() if tail else ""
        if token in _ABBREVIATIONS or re.fullmatch(r"\(?[a-zà-ÿ]\.", token):
            continue
        if re.fullmatch(r"\d{1,2}\.", token):
            continue  # ordinal (ex.: alemão/polonês "3. Mai")
        out.append(text[start:end].strip())
        start = m.end()
    rest = text[start:].strip()
    if rest:
        out.append(rest)
    return out


def segment_script(script: str) -> list[Segment]:
    paragraphs = [p for p in re.split(r"\n\s*\n|\r\n\s*\r\n", script or "") if p.strip()]
    if len(paragraphs) == 1 and "\n" in paragraphs[0]:
        paragraphs = [p for p in paragraphs[0].splitlines() if p.strip()]
    segs: list[Segment] = []
    for pi, para in enumerate(paragraphs):
        for sent in split_sentences(para):
            segs.append(Segment(index=len(segs), text=sent, paragraph=pi, words=word_count(sent)))
    return segs


def chunk_segments(segs: list[Segment], max_words: int = 650) -> list[list[Segment]]:
    """Blocos de frases para o planejamento de cenas (prefere quebrar entre parágrafos)."""
    chunks: list[list[Segment]] = []
    cur: list[Segment] = []
    count = 0
    for i, seg in enumerate(segs):
        cur.append(seg)
        count += seg.words
        nxt = segs[i + 1] if i + 1 < len(segs) else None
        para_break = nxt is not None and nxt.paragraph != seg.paragraph
        if count >= max_words or (count >= max_words * 0.7 and para_break):
            chunks.append(cur)
            cur, count = [], 0
    if cur:
        if chunks and count < max_words * 0.25:
            chunks[-1].extend(cur)
        else:
            chunks.append(cur)
    return chunks


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", "", s).strip()


def script_metrics(script: str, wpm: int, duration_min: float, duration_max: float) -> dict:
    segs = segment_script(script)
    all_words = words(script)
    n_words = len(all_words)
    minutes = n_words / max(wpm, 60)
    norm = Counter(_normalize(s.text) for s in segs if s.words >= 4)
    repeated_sentences = [
        {"text": next(s.text for s in segs if _normalize(s.text) == key), "count": c}
        for key, c in norm.most_common() if c > 1
    ][:10]
    tokens = [_normalize(w) for w in all_words]
    grams = Counter(" ".join(tokens[i:i + 5]) for i in range(max(0, len(tokens) - 4)))
    repeated_phrases = [{"text": g, "count": c} for g, c in grams.most_common(12) if c >= 3][:8]
    long_sentences = [s.index for s in segs if s.words > 40]
    paragraphs = len({s.paragraph for s in segs})
    return {
        "words": n_words,
        "characters": len(script or ""),
        "sentences": len(segs),
        "paragraphs": paragraphs,
        "words_per_minute": wpm,
        "estimated_minutes": round(minutes, 2),
        "target_min": duration_min,
        "target_max": duration_max,
        "within_target": duration_min <= minutes <= duration_max if n_words else False,
        "avg_sentence_words": round(n_words / len(segs), 1) if segs else 0,
        "long_sentences": len(long_sentences),
        "repeated_sentences": repeated_sentences,
        "repeated_phrases": repeated_phrases,
    }


# ------------------------------------------------------------------ legendas


def srt_timestamp(seconds: float) -> str:
    ms = max(0, int(round(seconds * 1000)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def timecode(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def caption_chunks(text: str, max_chars: int = 84) -> list[str]:
    ws = (text or "").split()
    chunks: list[str] = []
    cur: list[str] = []
    for w in ws:
        candidate = " ".join([*cur, w])
        if cur and len(candidate) > max_chars:
            chunks.append(" ".join(cur))
            cur = [w]
        else:
            cur.append(w)
            if re.search(r"[.!?…]$", w) and len(candidate) > max_chars * 0.5:
                chunks.append(" ".join(cur))
                cur = []
    if cur:
        chunks.append(" ".join(cur))
    return chunks


def wrap_two_lines(text: str, width: int = 42) -> str:
    if len(text) <= width:
        return text
    mid = len(text) // 2
    left = text.rfind(" ", 0, mid + 1)
    right = text.find(" ", mid)
    cut = left if left != -1 and (right == -1 or mid - left <= right - mid) else right
    if cut == -1:
        return text
    return text[:cut].strip() + "\n" + text[cut:].strip()


def build_srt(entries: list[tuple[float, float, str]]) -> str:
    """entries = (início, duração, texto) por cena; divide em legendas proporcionais ao texto."""
    lines: list[str] = []
    n = 1
    for start, duration, text in entries:
        chunks = caption_chunks(text)
        if not chunks or duration <= 0:
            continue
        total = sum(len(c) for c in chunks) or 1
        t = start
        for c in chunks:
            d = duration * len(c) / total
            lines += [str(n), f"{srt_timestamp(t)} --> {srt_timestamp(t + d)}", wrap_two_lines(c), ""]
            n += 1
            t += d
    return "\n".join(lines)
