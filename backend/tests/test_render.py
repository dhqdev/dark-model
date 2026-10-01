"""Vídeo final: monta sozinho depois da narração (ffmpeg, sem IA) e fica disponível para baixar."""

from __future__ import annotations

import subprocess

from app.jobs.worker import run_until_idle
from app.storage import get_storage

from .test_pipeline import SCRIPT, make_channel


def _streams(path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration", "-of",
                          "default=nw=1", str(path)], capture_output=True, text=True, check=True).stdout
    return {"types": [ln.split("=")[1] for ln in out.splitlines() if ln.startswith("codec_type")],
            "duration": float(next(ln.split("=")[1] for ln in out.splitlines() if ln.startswith("duration")))}


def test_final_video_is_assembled_after_narration(auth, fake):
    ch = make_channel(auth)
    pid = auth.post("/api/projects", json={"channel_id": ch["id"], "title": "Final", "script": SCRIPT}).json()["id"]
    # sem cenas: não dá para montar
    assert auth.post(f"/api/projects/{pid}/render").status_code == 400
    assert auth.post(f"/api/projects/{pid}/scenes/plan", json={}).status_code == 200
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    scenes = d["scenes_list"]
    # a IA escolheu transições, efeitos e textos em algumas cenas
    assert {s["transition"] for s in scenes} - {"dissolve"}
    assert any(s["sfx"] != "none" for s in scenes) and any(s["overlay_text"] for s in scenes)
    assert d["stages"]["render"]["can_render"] is False
    auth.post(f"/api/projects/{pid}/visuals", json={"scope": "missing"})
    run_until_idle()
    auth.post(f"/api/projects/{pid}/narration", json={"scope": "missing"})
    run_until_idle()  # narração termina → montagem automática

    d = auth.get(f"/api/projects/{pid}").json()
    render = d["stages"]["render"]
    assert render["complete"] is True and render["last"] is not None and render["outdated"] is False
    info = render["info"]
    assert info["auto"] is True and info["overlays"] >= 1 and info["sfx"] >= 1 and info["transitions"] >= 1
    final = render["last"]
    assert final["kind"] == "final" and final["mime"] == "video/mp4"
    total = sum(s["audio_duration"] for s in d["scenes_list"])
    r = auth.get(f"{final['url']}?download=1")
    assert r.status_code == 200 and "attachment" in r.headers.get("content-disposition", "")
    tmp = get_storage().tmp_dir() / "check.mp4"
    tmp.write_bytes(r.content)
    probe = _streams(tmp)
    assert sorted(probe["types"]) == ["audio", "video"]
    assert abs(probe["duration"] - total) < 0.25  # imagem e narração sincronizadas

    # mudar a edição de uma cena deixa o vídeo desatualizado; montar de novo substitui o anterior
    sid = d["scenes_list"][1]["id"]
    assert auth.patch(f"/api/scenes/{sid}", json={"transition": "fade to black", "sfx": "Impact",
                                                  "overlay_text": "Boêmia, 1907"}).status_code == 200
    s = next(x for x in auth.get(f"/api/projects/{pid}").json()["scenes_list"] if x["id"] == sid)
    assert (s["transition"], s["sfx"], s["overlay_text"]) == ("fadeblack", "impact", "Boêmia, 1907")
    assert auth.get(f"/api/projects/{pid}").json()["stages"]["render"]["outdated"] is True
    assert auth.post(f"/api/projects/{pid}/render").status_code == 200
    run_until_idle()
    render = auth.get(f"/api/projects/{pid}").json()["stages"]["render"]
    assert render["outdated"] is False and render["last"]["id"] != final["id"]
    assert render["info"]["auto"] is False
