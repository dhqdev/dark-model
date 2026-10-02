"""Piloto automático: do roteiro ao ZIP sozinho, pausando em falha e em alto risco de política."""

from __future__ import annotations

from app.db import session_scope
from app.jobs.worker import run_until_idle
from app.models import Project

from .test_pipeline import SCRIPT, make_channel


def _project(auth, title="Piloto"):
    ch = make_channel(auth)
    return auth.post("/api/projects", json={"channel_id": ch["id"], "title": title, "script": SCRIPT}).json()["id"]


def test_autopilot_runs_every_stage(auth, fake):
    pid = _project(auth)
    d = auth.post(f"/api/projects/{pid}/autopilot", json={"action": "start"}).json()
    assert d["autopilot"]["active"] is True and d["autopilot"]["step"] == "analysis"
    run_until_idle()

    d = auth.get(f"/api/projects/{pid}").json()
    ap, st = d["autopilot"], d["stages"]
    assert ap["status"] == "done" and ap["active"] is False, ap
    assert st["script"]["analysis_fresh"] and st["scenes"]["count"] > 0
    assert st["narration"]["ready"] == st["narration"]["total"]
    assert st["visuals"]["ready"] == st["visuals"]["total"]
    assert st["render"]["last"] is not None and st["render"]["outdated"] is False
    assert st["metadata"]["ready"] and st["thumbnail"]["concepts"] > 0
    assert st["export"]["count"] == 1 and st["export"]["outdated"] is False
    # cada etapa rodou uma vez só (nada pago em dobro)
    assert fake.count("POST /audio/speech") == st["narration"]["total"]
    assert fake.count("POST /images") == st["visuals"]["total"] + st["thumbnail"]["images"]

    # ligar de novo com tudo pronto: termina na hora, sem gastar
    calls = len(fake.calls)
    d = auth.post(f"/api/projects/{pid}/autopilot", json={"action": "start"}).json()
    run_until_idle()
    assert auth.get(f"/api/projects/{pid}").json()["autopilot"]["status"] == "done"
    assert len(fake.calls) == calls


def test_autopilot_pauses_on_failure_and_resumes(auth, fake):
    pid = _project(auth)
    fake.fail("POST /images", 402, times=1)  # sem saldo: não repete sozinho
    auth.post(f"/api/projects/{pid}/autopilot", json={"action": "start"})
    run_until_idle()
    ap = auth.get(f"/api/projects/{pid}").json()["autopilot"]
    assert ap["status"] == "paused" and ap["active"] is False and ap["step"] == "visuals"
    assert "Visuais" in ap["error"] or "falharam" in ap["error"]

    # retomar refaz só o que falta
    images = fake.count("POST /images")
    auth.post(f"/api/projects/{pid}/autopilot", json={"action": "start"})
    run_until_idle()
    d = auth.get(f"/api/projects/{pid}").json()
    assert d["autopilot"]["status"] == "done"
    assert fake.count("POST /images") == images + 1 + d["stages"]["thumbnail"]["images"]


def test_autopilot_stops_on_high_risk_until_confirmed(auth, fake):
    pid = _project(auth)
    auth.post(f"/api/projects/{pid}/analyze")
    run_until_idle()
    with session_scope() as db:
        p = db.get(Project, pid)
        p.analysis = {**p.analysis, "ai": {**p.analysis["ai"], "verdict": "high_risk"}}
    d = auth.post(f"/api/projects/{pid}/autopilot", json={"action": "start"}).json()
    assert d["autopilot"]["status"] == "paused" and d["autopilot"]["reason"] == "risk"
    assert fake.count("POST /chat/completions") == 1  # nada além da análise

    auth.post(f"/api/projects/{pid}/autopilot", json={"action": "start", "ignore_risk": True})
    run_until_idle()
    assert auth.get(f"/api/projects/{pid}").json()["autopilot"]["status"] == "done"


def test_autopilot_stop(auth, fake):
    pid = _project(auth)
    auth.post(f"/api/projects/{pid}/autopilot", json={"action": "start"})
    d = auth.post(f"/api/projects/{pid}/autopilot", json={"action": "stop"}).json()
    assert d["autopilot"]["active"] is False and d["autopilot"]["status"] == "stopped"
    run_until_idle()  # a análise já na fila termina, mas nada novo é enfileirado
    d = auth.get(f"/api/projects/{pid}").json()
    assert d["stages"]["scenes"]["count"] == 0 and d["autopilot"]["status"] == "stopped"


def test_autopilot_needs_script(auth, fake):
    ch = make_channel(auth)
    pid = auth.post("/api/projects", json={"channel_id": ch["id"], "title": "Vazio"}).json()["id"]
    r = auth.post(f"/api/projects/{pid}/autopilot", json={"action": "start"})
    assert r.status_code == 400 and "roteiro" in r.json()["detail"]
