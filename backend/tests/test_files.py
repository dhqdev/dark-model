"""Arquivos do projeto: tamanho por parte do processo e exclusão de cada parte."""

from __future__ import annotations

from app.jobs.worker import run_until_idle
from app.storage import get_storage

from .test_pipeline import SCRIPT, make_channel


def _part(report: dict, key: str) -> dict:
    return next(p for p in report["parts"] if p["key"] == key)


def test_sizes_and_delete_each_part(auth, fake):
    ch = make_channel(auth)
    pid = auth.post("/api/projects", json={"channel_id": ch["id"], "title": "Arquivos", "script": SCRIPT}).json()["id"]
    for path, body in (("analyze", None), ("scenes/plan", {}), ("visuals", {"scope": "missing"}),
                       ("narration", {}), ("thumbnails", {}), ("metadata", None), ("export", {})):
        assert auth.post(f"/api/projects/{pid}/{path}", json=body or {}).status_code == 200
        run_until_idle()
    # refaz uma imagem: a anterior vira "versão antiga"
    scene = auth.get(f"/api/projects/{pid}").json()["scenes_list"][0]
    auth.post(f"/api/scenes/{scene['id']}/visual", json={"force": True})
    run_until_idle()

    rep = auth.get(f"/api/projects/{pid}/storage").json()
    assert rep["total_bytes"] > 0 and rep["disk_bytes"] >= rep["total_bytes"]
    for key in ("images", "motion", "videos", "narration", "final", "thumbnails", "exports"):
        assert _part(rep, key)["bytes"] > 0, key
    assert _part(rep, "old_versions")["count"] >= 1
    # o tamanho aparece na lista de projetos e no projeto
    listed = next(p for p in auth.get(f"/api/projects?channel_id={ch['id']}").json() if p["id"] == pid)
    assert listed["size_bytes"] == rep["total_bytes"]
    assert auth.get(f"/api/projects/{pid}").json()["size_bytes"] == rep["total_bytes"]

    # arquivo solto no disco (sobra de tarefa cancelada)
    stray = get_storage().path(f"projects/{pid}/scenes/sobra.tmp")
    stray.write_bytes(b"x" * 1000)
    rep = auth.get(f"/api/projects/{pid}/storage").json()
    assert _part(rep, "orphans")["bytes"] == 1000

    def delete(key: str) -> dict:
        r = auth.delete(f"/api/projects/{pid}/storage/{key}")
        assert r.status_code == 200, r.text
        return r.json()

    assert delete("orphans")["freed_bytes"] == 1000 and not stray.exists()
    old = _part(rep, "old_versions")["bytes"]
    assert delete("old_versions")["freed_bytes"] == old
    # o que está em uso continua: o vídeo final ainda está completo
    d = auth.get(f"/api/projects/{pid}").json()
    assert all(s["visual_ready"] for s in d["scenes_list"])

    r = delete("final")
    assert r["freed_bytes"] > 0 and _part(r["storage"], "final")["bytes"] == 0
    assert auth.get(f"/api/projects/{pid}").json()["stages"]["render"]["last"] is None

    delete("narration")
    d = auth.get(f"/api/projects/{pid}").json()
    assert d["stages"]["narration"]["ready"] == 0 and all(s["audio"] is None for s in d["scenes_list"])

    delete("images")
    d = auth.get(f"/api/projects/{pid}").json()
    assert all(s["image"] is None for s in d["scenes_list"]) and d["stages"]["visuals"]["ready"] == 0

    delete("thumbnails")
    delete("metadata")
    delete("analysis")
    d = auth.get(f"/api/projects/{pid}").json()
    assert d["concepts"] == [] and d["metadata_suggestions"] is None and d["selected_title"] == ""
    assert d["analysis"] is None

    r = delete("scenes")
    assert r["storage"]["parts"] and auth.get(f"/api/projects/{pid}").json()["scenes_list"] == []
    delete("exports")
    rep = auth.get(f"/api/projects/{pid}/storage").json()
    assert rep["total_bytes"] == 0 and rep["disk_bytes"] == 0
    # o roteiro continua
    assert auth.get(f"/api/projects/{pid}").json()["script"].startswith("In 1907")

    assert auth.delete(f"/api/projects/{pid}/storage/nada").status_code == 404
