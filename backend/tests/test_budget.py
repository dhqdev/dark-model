"""Teto por vídeo em reais: o plano de cada nível é ajustado para caber, e a produção segue o plano."""

from __future__ import annotations

from app.jobs.worker import run_until_idle
from app.pipeline import text
from app.pipeline.scenes import limit_scene_count

from .test_pipeline import SCRIPT, make_channel

# ~19 min de narração (o tamanho de um vídeo real do canal)
LONG_SCRIPT = "\n\n".join([SCRIPT] * 9)


def _project(auth, script=LONG_SCRIPT, quality="BALANCED"):
    ch = make_channel(auth)
    p = auth.post("/api/projects", json={"channel_id": ch["id"], "title": "Long one", "script": script}).json()
    if quality != "BALANCED":
        assert auth.patch(f"/api/projects/{p['id']}", json={"quality": quality}).status_code == 200
    return p["id"]


def test_tiers_fit_their_caps(auth, fake):
    pid = _project(auth)
    est = auth.get(f"/api/projects/{pid}/estimate").json()
    assert est["fx"]["rate"] == 5.0 and est["fx"]["source"] == "default"
    bal, prem, eco = est["tiers"]["BALANCED"], est["tiers"]["PREMIUM"], est["tiers"]["ECONOMY"]
    assert bal["cap_brl"] == 20 and prem["cap_brl"] == 50 and eco["cap_brl"] is None
    for tier in (bal, prem):
        assert tier["fits"] is True
        assert tier["total"] <= tier["cap_usd"] and tier["total_brl"] <= tier["cap_brl"]
        assert round(tier["total"] * 5.0, 2) == tier["total_brl"]
    # o Premium sem teto passaria de R$ 50: o plano foi enxugado e diz o que mudou
    assert prem["adjustments"]
    assert eco["fits"] is None and eco["adjustments"] == []
    # cada linha tem chave estável (as tabelas alinham as linhas pela chave)
    assert [ln["key"] for ln in bal["lines"]][:5] == ["script", "scenes", "images", "videos", "motion"]


def test_cap_too_low_is_reported(auth, fake):
    pid = _project(auth)
    r = auth.put("/api/settings/tiers", json={"tiers": {"BALANCED": {"cap_brl": 1}}})
    assert r.status_code == 200, r.text
    bal = auth.get(f"/api/projects/{pid}/estimate").json()["tiers"]["BALANCED"]
    assert bal["fits"] is False
    assert any("passa do teto" in a for a in bal["adjustments"])
    # o plano mais enxuto: cenas longas e o modelo de imagem mais barato
    assert bal["plan"]["scene_seconds"] == 20
    assert bal["plan"]["image_model"] == "black-forest-labs/flux.2-klein-4b"
    # 0 = sem teto
    auth.put("/api/settings/tiers", json={"tiers": {"BALANCED": {"cap_brl": 0}}})
    bal = auth.get(f"/api/projects/{pid}/estimate").json()["tiers"]["BALANCED"]
    assert bal["fits"] is None and bal["plan"]["image_model"] == "google/gemini-2.5-flash-image"


def test_production_follows_the_plan(auth, fake):
    auth.put("/api/settings/tiers", json={"tiers": {"BALANCED": {"cap_brl": 1}}})
    pid = _project(auth, script=SCRIPT)
    est = auth.get(f"/api/projects/{pid}/estimate").json()["tiers"]["BALANCED"]
    assert auth.post(f"/api/projects/{pid}/scenes/plan", json={}).status_code == 200
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    assert d["plan"]["tier"] == "BALANCED"
    assert d["plan"]["image_model"] == est["plan"]["image_model"]
    assert auth.post(f"/api/projects/{pid}/visuals", json={"scope": "missing"}).status_code == 200
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    images = [s["image"] for s in d["scenes_list"] if s.get("image")]
    assert images and {a["model"] for a in images} == {d["plan"]["image_model"]}


def test_manual_exchange_rate(auth, fake):
    r = auth.put("/api/settings/fx", json={"manual_rate": 6.0})
    assert r.status_code == 200 and r.json()["source"] == "manual" and r.json()["rate"] == 6.0
    pid = _project(auth, script=SCRIPT)
    est = auth.get(f"/api/projects/{pid}/estimate").json()
    assert est["fx"]["rate"] == 6.0
    assert est["tiers"]["BALANCED"]["cap_usd"] == round(20 / 6.0, 4)
    auth.put("/api/settings/fx", json={"manual_rate": None})
    assert auth.get("/api/settings").json()["fx"]["source"] == "default"


def test_limit_scene_count_merges_shortest_neighbours():
    segs = {s.index: s for s in text.segment_script(SCRIPT)}
    first, last = min(segs), max(segs)
    items = [{"start": i, "end": i, "prompt": f"p{i}", "asset_type": "IMAGE_MOTION"} for i in range(first, last + 1)]
    out = limit_scene_count(items, 5, segs)
    assert len(out) == 5
    # cobertura contínua, sem buracos
    assert out[0]["start"] == first and out[-1]["end"] == last
    assert all(a["end"] + 1 == b["start"] for a, b in zip(out, out[1:]))


def test_live_exchange_rate_is_cached(auth, fake, monkeypatch):
    import httpx

    from app import fx
    from app.config import get_settings
    from app.db import SessionLocal

    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        if "awesomeapi" in url:
            return httpx.Response(200, json={"USDBRL": {"bid": "5.3812"}}, request=httpx.Request("GET", url))
        raise httpx.ConnectError("offline")

    monkeypatch.setenv("FX_AUTO", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(fx.httpx, "get", fake_get)
    db = SessionLocal()
    try:
        r = fx.get_rate(db)
        assert r["source"] == "live" and r["rate"] == 5.3812
    finally:
        db.close()
    db = SessionLocal()
    try:
        assert fx.get_rate(db)["rate"] == 5.3812 and len(calls) == 1  # cache de 12 h
    finally:
        db.close()
    get_settings.cache_clear()


def test_premium_fits_even_with_expensive_voice_and_text(auth, fake, monkeypatch):
    """Premium passava de R$ 500: voz, texto e vídeo também entram no ajuste ao teto."""
    from tests import fake_openrouter as fo

    tts = next(m for m in fo.SPEECH_MODELS if m["id"] == "openai/gpt-4o-mini-tts")
    monkeypatch.setitem(tts, "pricing", {"prompt": "0.0000006", "completion": "0.01"})  # ~R$ 1.900 de narração
    opus = next(m for m in fo.TEXT_MODELS if "opus" in m["id"])
    monkeypatch.setitem(opus, "pricing", {"prompt": "0.0003", "completion": "0.0015"})
    pid = _project(auth, quality="PREMIUM")
    prem = auth.get(f"/api/projects/{pid}/estimate").json()["tiers"]["PREMIUM"]
    assert prem["fits"] is True and prem["total_brl"] <= 50
    assert any(a.startswith("narração:") for a in prem["adjustments"])
    assert any(a.startswith("texto:") for a in prem["adjustments"])
    # a produção usa o plano: análise do roteiro com o modelo de texto escolhido e narração com a voz escolhida
    assert auth.post(f"/api/projects/{pid}/analyze").status_code == 200
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    assert d["plan"]["text_model"] == prem["plan"]["text_model"] != opus["id"]
    chat = [b for m, p, b in fake.calls if p == "/chat/completions"]
    assert chat[-1]["model"] == prem["plan"]["text_model"]


def test_planned_video_scenes_are_trimmed_to_fit(auth, fake):
    auth.put("/api/settings/tiers", json={"tiers": {"PREMIUM": {"cap_brl": 0}}})
    pid = _project(auth, script=SCRIPT, quality="PREMIUM")
    assert auth.post(f"/api/projects/{pid}/scenes/plan", json={}).status_code == 200
    run_until_idle()
    scenes = auth.get(f"/api/projects/{pid}").json()["scenes_list"]
    videos = [s for s in scenes if s["asset_type"] == "VIDEO"]
    assert len(videos) >= 2
    # a primeira cena de vídeo fica travada: o usuário quer o vídeo nela
    assert auth.patch(f"/api/scenes/{videos[0]['id']}", json={"locked": True}).status_code == 200
    # teto que só cabe com menos vídeo IA
    est = auth.get(f"/api/projects/{pid}/estimate").json()["tiers"]["PREMIUM"]
    auth.put("/api/settings/tiers", json={"tiers": {"PREMIUM": {"cap_brl": round(est['total_brl'] * 0.7, 2)}}})
    prem = auth.get(f"/api/projects/{pid}/estimate").json()["tiers"]["PREMIUM"]
    keep = prem["plan"]["video_keep"]
    assert prem["fits"] is True and 1 <= keep < len(videos)
    assert any("vídeo IA em" in a for a in prem["adjustments"])
    assert auth.post(f"/api/projects/{pid}/visuals", json={"scope": "missing"}).status_code == 200
    run_until_idle()
    after = auth.get(f"/api/projects/{pid}").json()["scenes_list"]
    left = [s for s in after if s["asset_type"] == "VIDEO"]
    assert len(left) == keep and videos[0]["id"] in {s["id"] for s in left}
    converted = [s for s in after if s["id"] in {v["id"] for v in videos} and s["asset_type"] == "IMAGE_MOTION"]
    assert converted and "teto" in converted[0]["asset_type_reason"]
