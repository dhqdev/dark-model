"""Fluxo completo: canal → Skill → projeto → roteiro → cenas → visuais → narração → thumbnail →
metadados → exportação → custos → aprendizado → consolidação da Skill."""

from __future__ import annotations

import io
import zipfile

from app.jobs.worker import run_until_idle
from app.pipeline import text

SCRIPT = """In 1907, a team of miners in the mountains of Bohemia broke through a wall of solid rock. Behind it, they found a room that should not have existed. The walls were smooth, the floor was dry, and in the center stood a wooden chest sealed with wax.

Nobody in the village could explain who built the chamber. The local priest wrote in his diary that the miners refused to return to the tunnel. Two weeks later, the entrance was filled with gravel by order of the mayor. For decades, the story survived only as a rumor told in taverns.

Then, in 1956, a young historian named Anna found the priest's diary in a church archive. She noticed a detail everyone had ignored. The diary described symbols carved above the chest, and those symbols matched a medieval guild that had vanished in 1420. Anna spent six years tracing the guild through tax records, letters and court documents. She discovered that its members were bookbinders who protected forbidden manuscripts during the Hussite wars.

In 1962, Anna convinced the authorities to reopen the tunnel. The chamber was still there, but the chest was gone. Only the wax seal remained on the floor, broken in half. Someone had entered the room after 1907 and left no trace. Anna never found out who it was. But in her final notebook, she wrote a single sentence that still puzzles researchers today. The library was never lost, it was moved."""


def make_channel(auth, **extra):
    body = {"name": "Lost Archives", "language": "en-US", "country": "US", "audience": "Adults who love history mysteries",
            "niche": "historical mysteries", "style": "investigative documentary", "tone": "mysterious, calm",
            "duration_min": 15, "duration_max": 25, "visual_style": "cinematic, candlelight, muted earth tones",
            "tts_voice": "onyx", **extra}
    r = auth.post("/api/channels", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_full_pipeline(auth, fake):
    ch = make_channel(auth)
    skill = auth.get(f"/api/channels/{ch['id']}/skill").json()
    assert skill["current"]["version"] == 1 and "Lost Archives" in skill["current"]["content"]

    p = auth.post("/api/projects", json={"channel_id": ch["id"], "title": "The Bohemian Chamber", "script": SCRIPT}).json()
    pid = p["id"]
    assert p["quality"] == "BALANCED"

    # estimativa antes de gerar: três níveis, preços do catálogo
    est = auth.get(f"/api/projects/{pid}/estimate").json()
    assert set(est["tiers"]) == {"ECONOMY", "BALANCED", "PREMIUM"}
    for tier in est["tiers"].values():
        assert tier["total"] > 0
        assert all(line["source"] in {"live", "history", "heuristic", "free", "unavailable"} for line in tier["lines"])
    assert est["tiers"]["ECONOMY"]["total"] < est["tiers"]["BALANCED"]["total"] < est["tiers"]["PREMIUM"]["total"]
    assert est["tiers"]["BALANCED"]["models"]["text"] == "anthropic/claude-sonnet-4.5"
    assert est["tiers"]["PREMIUM"]["models"]["text"] == "anthropic/claude-opus-4.5"
    assert est["tiers"]["ECONOMY"]["models"]["text"] == "google/gemini-3-flash-preview"
    # cenas mais longas nos níveis baratos = menos imagens
    assert est["tiers"]["ECONOMY"]["scenes"] <= est["tiers"]["BALANCED"]["scenes"] <= est["tiers"]["PREMIUM"]["scenes"]

    # 1. roteiro
    assert auth.post(f"/api/projects/{pid}/analyze").status_code == 200
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    assert d["analysis"]["ai"]["verdict"] == "needs_revision"
    assert d["analysis"]["metrics"]["words"] == text.word_count(SCRIPT)
    assert d["stages"]["script"]["analysis_fresh"] is True

    # 2. cenas: cobrem todas as frases, em ordem
    # o roteiro de teste é curto: com 3% de vídeo IA nenhuma cena teria vídeo; o teste precisa de algumas
    auth.put("/api/settings/tiers", json={"tiers": {"BALANCED": {"video_share": 0.3}}})
    assert auth.post(f"/api/projects/{pid}/scenes/plan", json={}).status_code == 200
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    scenes = d["scenes_list"]
    sentences = [s.text for s in text.segment_script(SCRIPT)]
    assert " ".join(s["narration"] for s in scenes) == " ".join(sentences)
    assert any(s["asset_type"] == "VIDEO" for s in scenes)
    assert all(s["est_duration"] > 0 and s["prompt"] for s in scenes)
    # replanejar sem confirmar é bloqueado
    assert auth.post(f"/api/projects/{pid}/scenes/plan", json={}).status_code == 409

    # 3. visuais (imagem → movimento local / vídeo IA)
    r = auth.post(f"/api/projects/{pid}/visuals", json={"scope": "missing"}).json()
    assert r["job"]["is_group"] is True
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    assert d["stages"]["visuals"]["ready"] == len(scenes)
    for s in d["scenes_list"]:
        assert s["image"]["width"] == 1920 and s["image"]["height"] == 1080
        expected = {"VIDEO": "video", "IMAGE_MOTION": "motion"}.get(s["asset_type"])
        if expected:
            assert s["clip"]["kind"] == expected
            assert auth.get(s["clip"]["url"]).headers["content-type"] == "video/mp4"
    group = auth.get(f"/api/jobs/{r['job']['id']}").json()
    assert group["status"] == "succeeded" and all(c["status"] == "succeeded" for c in group["children"])
    # nada para refazer
    assert auth.post(f"/api/projects/{pid}/visuals", json={"scope": "missing"}).json()["job"] is None

    # 4. narração por cena (duração real medida) + movimento sincronizado
    auth.post(f"/api/projects/{pid}/narration", json={})
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    assert d["stages"]["narration"]["ready"] == len(scenes)
    for s in d["scenes_list"]:
        assert s["audio_duration"] and s["audio_ok"]
        if s["asset_type"] == "IMAGE_MOTION":
            assert abs(s["clip"]["duration"] - s["audio_duration"]) < 0.35
    tts_calls = [b for m, path, b in fake.calls if path == "/audio/speech"]
    assert all(b["voice"] == "onyx" and b["response_format"] == "mp3" for b in tts_calls)

    # 5. thumbnails: conceitos + variações
    auth.post(f"/api/projects/{pid}/thumbnails", json={})
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    assert len(d["concepts"]) == 3 and all(len(c["images"]) == 2 for c in d["concepts"])
    concept = d["concepts"][0]
    r = auth.post(f"/api/thumbnails/{concept['id']}/select", json={"asset_id": concept["images"][1]["id"]})
    assert r.json()["selected_asset_id"] == concept["images"][1]["id"]

    # 6. metadados com capítulos reais
    auth.post(f"/api/projects/{pid}/metadata")
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    meta = d["metadata_suggestions"]
    assert len(meta["titles"]) == 8 and d["selected_title"]
    assert meta["chapters"][0]["time"] == "0:00" and "0:00" in d["description"]
    assert meta["timeline_source"] == "audio"
    auth.patch(f"/api/projects/{pid}", json={"selected_title": meta["titles"][2]["title"]})

    # edição de cena gera sinal para a Skill
    first = d["scenes_list"][0]
    r = auth.patch(f"/api/scenes/{first['id']}", json={"prompt": first["prompt"] + ", extreme close-up"})
    assert r.json()["image_ok"] is False  # prompt mudou → visual desatualizado

    # 7. exportação
    auth.post(f"/api/projects/{pid}/export", json={})
    run_until_idle()
    exports = auth.get(f"/api/projects/{pid}/exports").json()
    assert len(exports) == 1
    z = zipfile.ZipFile(io.BytesIO(auth.get(exports[0]["url"]).content))
    names = z.namelist()
    root = names[0].split("/")[0]
    for required in ("LEIA-ME.txt", "timeline.json", "projeto.json", "01_roteiro/roteiro.txt", "02_cenas/cenas.csv",
                     "04_narracao/narracao_completa.mp3", "05_legendas/legendas.srt", "07_metadados/descricao.txt"):
        assert f"{root}/{required}" in names, required
    assert any(n.endswith("_ESCOLHIDA.jpg") for n in names)
    assert sum(1 for n in names if n.startswith(f"{root}/04_narracao/cena_")) == len(scenes)

    # 8. custos reais por etapa = o que a "OpenRouter" cobrou
    costs = auth.get(f"/api/projects/{pid}/costs").json()
    by_stage = {s["stage"]: s for s in costs["stages"]}
    for stage in ("script", "scenes", "visuals", "narration", "thumbnail", "metadata"):
        assert by_stage[stage]["cost"] > 0, stage
    assert by_stage["script"]["tokens_in"] > 0 and by_stage["script"]["tokens_out"] > 0
    summary = auth.get("/api/usage/summary").json()
    assert abs(summary["total"]["cost"] - fake.spent) < 1e-6
    assert summary["channels"][0]["name"] == "Lost Archives"
    bal = auth.get("/api/usage/balance").json()
    assert bal["source"] == "key_limit" and abs(bal["balance"] - (10 - fake.spent)) < 1e-4

    # 9. aprendizado automático após exportar → aprovar → consolidar nova versão da Skill
    learnings = auth.get(f"/api/channels/{ch['id']}/learnings").json()
    assert len(learnings) == 2 and all(x["status"] == "proposed" for x in learnings)
    learn_prompt = next(b for m, path, b in reversed(fake.calls) if path == "/chat/completions"
                        and b["response_format"]["json_schema"]["name"] == "learnings")
    assert "extreme close-up" in learn_prompt["messages"][1]["content"]
    auth.patch(f"/api/channels/learnings/{learnings[0]['id']}", json={"status": "accepted"})
    auth.post(f"/api/channels/{ch['id']}/skill/consolidate")
    run_until_idle()
    skill = auth.get(f"/api/channels/{ch['id']}/skill").json()
    assert skill["current"]["version"] == 2 and skill["current"]["source"] == "consolidation"
    statuses = {x["id"]: x["status"] for x in auth.get(f"/api/channels/{ch['id']}/learnings").json()}
    assert statuses[learnings[0]["id"]] == "merged" and statuses[learnings[1]["id"]] == "proposed"

    # Skill entra no contexto das próximas chamadas
    auth.post(f"/api/projects/{pid}/analyze")
    run_until_idle()
    last = next(b for m, path, b in reversed(fake.calls) if path == "/chat/completions")
    assert "CHANNEL SKILL v2" in last["messages"][1]["content"]

    dash = auth.get("/api/dashboard").json()
    assert dash["counts"]["projects"] == 1 and dash["costs"]["total"]["cost"] > 0


def test_economy_tier_has_no_ai_video(auth, fake):
    ch = make_channel(auth, default_quality="ECONOMY")
    p = auth.post("/api/projects", json={"channel_id": ch["id"], "title": "Eco", "script": SCRIPT}).json()
    auth.post(f"/api/projects/{p['id']}/scenes/plan", json={})
    run_until_idle()
    scenes = auth.get(f"/api/projects/{p['id']}").json()["scenes_list"]
    assert scenes and all(s["asset_type"] != "VIDEO" for s in scenes)
    plan_call = next(b for m, path, b in fake.calls if path == "/chat/completions")
    assert plan_call["model"] == "google/gemini-3-flash-preview"
