"""Caminhos menos comuns dos providers: imagem via chat, áudio PCM, custo pendente."""

from __future__ import annotations

import io
import math
import struct
import tempfile
from pathlib import Path

from PIL import Image

from app import media, usage as usage_ledger
from app.db import session_scope
from app.models import UsageRecord
from app.providers import registry


def test_image_via_chat_for_models_outside_images_api(fake, client):
    res = registry.image().generate(model="openai/gpt-5-image-mini", prompt="a lighthouse at night", aspect_ratio="16:9")
    assert res.mime == "image/png" and Image.open(io.BytesIO(res.data)).size[0] > 100
    assert res.usage.cost_usd and res.usage.cost_source == "reported"
    call = next(b for m, p, b in fake.calls if p == "/chat/completions")
    assert call["modalities"] == ["image", "text"] and call["image_config"] == {"aspect_ratio": "16:9"}


def test_pcm_audio_is_converted_to_mp3():
    rate = 24000
    pcm = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(rate))
    mp3 = media.to_mp3(pcm, "audio/pcm; rate=24000")
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "a.mp3"
        f.write_bytes(mp3)
        assert abs((media.probe_duration(f) or 0) - 1.0) < 0.15


def test_pending_costs_are_reconciled(fake, client):
    gid = fake._gen("tts-", 0.0123)
    with session_scope() as db:
        db.add(UsageRecord(stage="narration", operation="tts", model="openai/gpt-4o-mini-tts", generation_id=gid,
                           cost_source="pending", units=100, unit="chars"))
    with session_scope() as db:
        assert usage_ledger.reconcile_pending(db, registry.openrouter_client()) == 1
    with session_scope() as db:
        rec = db.query(UsageRecord).filter_by(generation_id=gid).one()
        assert rec.cost_usd == 0.0123 and rec.cost_source == "generation"


def test_gemini_tts_uses_pcm_and_unknown_models_learn_the_format(fake, client):
    """Caso real: 'Gemini TTS only supports response_format="pcm". Got "mp3".' — 60 narrações falharam."""
    tts = registry.tts()
    type(tts)._formats.clear()
    res = tts.synthesize(model="google/gemini-3.1-flash-tts-preview", text="Dez de maio de 1869.", voice="Kore")
    assert res.mime == "audio/mpeg"
    speech = [b for m, p, b in fake.calls if p == "/audio/speech"]
    assert [b["response_format"] for b in speech] == ["pcm"]  # sem tentativa perdida em MP3
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "a.mp3"
        out.write_bytes(res.data)
        assert media.probe(out)["duration"] > 0.5

    # outro modelo que só aceita PCM: aprende pelo erro 400 e não erra de novo
    fake.calls.clear()
    tts.synthesize(model="acme/pcm-only-tts", text="Primeira cena.", voice="a")
    tts.synthesize(model="acme/pcm-only-tts", text="Segunda cena.", voice="a")
    formats = [b["response_format"] for m, p, b in fake.calls if p == "/audio/speech"]
    assert formats == ["mp3", "pcm", "pcm"]
