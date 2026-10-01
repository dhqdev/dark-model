"""Fila: retry apenas do que falhou, erros da OpenRouter, limite de gasto, cancelamento, recuperação."""

from __future__ import annotations

from datetime import timedelta

from app.db import session_scope
from app.jobs import queue
from app.jobs.worker import run_until_idle
from app.models import Job, utcnow
from tests.test_pipeline import SCRIPT, make_channel


def _project_with_scenes(auth):
    ch = make_channel(auth)
    p = auth.post("/api/projects", json={"channel_id": ch["id"], "title": "Queue", "script": SCRIPT}).json()
    auth.post(f"/api/projects/{p['id']}/scenes/plan", json={})
    run_until_idle()
    return ch, p


def test_transient_errors_are_retried_by_client(auth, fake):
    _, p = _project_with_scenes(auth)
    fake.fail("POST /images", 503, times=1)
    scene = auth.get(f"/api/projects/{p['id']}").json()["scenes_list"][0]
    auth.post(f"/api/scenes/{scene['id']}/visual", json={"step": "image"})
    run_until_idle()
    assert fake.count("POST /images") == 2
    assert auth.get(f"/api/projects/{p['id']}").json()["scenes_list"][0]["image_ok"]


def test_only_failed_steps_are_retried(auth, fake):
    _, p = _project_with_scenes(auth)
    n = len(auth.get(f"/api/projects/{p['id']}").json()["scenes_list"])
    fake.fail("POST /images", 402, times=2)  # sem saldo: não repete sozinho
    group = auth.post(f"/api/projects/{p['id']}/visuals", json={}).json()["job"]
    run_until_idle()
    g = auth.get(f"/api/jobs/{group['id']}").json()
    assert g["status"] == "failed"
    failed = [c for c in g["children"] if c["status"] == "failed"]
    assert len(failed) == 2 and "Saldo insuficiente" in failed[0]["error"]
    calls_before = fake.count("POST /images")
    r = auth.post(f"/api/jobs/{group['id']}/retry").json()
    assert r["requeued"] == 2
    run_until_idle()
    assert fake.count("POST /images") == calls_before + 2  # só as duas imagens que falharam
    g = auth.get(f"/api/jobs/{group['id']}").json()
    assert g["status"] == "succeeded"
    d = auth.get(f"/api/projects/{p['id']}").json()
    assert d["stages"]["visuals"]["ready"] == n


def test_retryable_job_error_is_rescheduled(auth, fake):
    _, p = _project_with_scenes(auth)
    fake.fail("POST /chat/completions", 500, times=4)  # esgota as tentativas automáticas do cliente
    auth.post(f"/api/projects/{p['id']}/analyze")
    run_until_idle()
    jobs = auth.get(f"/api/projects/{p['id']}/jobs").json()
    job = next(j for j in jobs if j["kind"] == "script.analyze")
    assert job["status"] == "queued" and job["run_after"] and "nova tentativa" in job["message"]
    with session_scope() as db:
        db.get(Job, job["id"]).run_after = utcnow() - timedelta(seconds=1)
    run_until_idle()
    assert auth.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"


def test_budget_limit_blocks_paid_jobs(auth, fake):
    _, p = _project_with_scenes(auth)
    assert auth.put("/api/settings/budget", json={"daily_limit_usd": 0.000001}).status_code == 200
    auth.post(f"/api/projects/{p['id']}/metadata")
    run_until_idle()
    job = next(j for j in auth.get(f"/api/projects/{p['id']}/jobs").json() if j["kind"] == "metadata.generate")
    assert job["status"] == "failed" and "Limite diário" in job["error"]
    auth.put("/api/settings/budget", json={"daily_limit_usd": None, "project_limit_usd": 1000})
    auth.post(f"/api/jobs/{job['id']}/retry")
    run_until_idle()
    assert auth.get(f"/api/jobs/{job['id']}").json()["status"] == "succeeded"


def test_cancel_dedupe_and_stale_recovery(auth, fake):
    _, p = _project_with_scenes(auth)
    j1 = auth.post(f"/api/projects/{p['id']}/metadata").json()["job"]
    j2 = auth.post(f"/api/projects/{p['id']}/metadata").json()["job"]
    assert j1["id"] == j2["id"]  # clique duplo não duplica tarefa
    assert auth.post(f"/api/jobs/{j1['id']}/cancel").json()["job"]["status"] == "canceled"
    run_until_idle()
    assert fake.count("POST /chat/completions") == 1  # só a divisão em cenas

    with session_scope() as db:
        job = queue.enqueue(db, "script.analyze", label="x", project_id=p["id"], channel_id=p["channel_id"])
        job_id = job.id
    claimed = queue.claim("w-test", {"llm"})
    assert claimed == job_id
    with session_scope() as db:
        db.get(Job, job_id).heartbeat_at = utcnow() - timedelta(minutes=30)
        assert queue.recover_stale(db, 300) == 1
    with session_scope() as db:
        assert db.get(Job, job_id).status == "queued"


def test_project_deletion_removes_files(auth, fake):
    _, p = _project_with_scenes(auth)
    scene = auth.get(f"/api/projects/{p['id']}").json()["scenes_list"][0]
    auth.post(f"/api/scenes/{scene['id']}/visual", json={"step": "image"})
    run_until_idle()
    from app.storage import get_storage

    assert get_storage().path(f"projects/{p['id']}").exists()
    assert auth.delete(f"/api/projects/{p['id']}").status_code == 200
    assert not get_storage().path(f"projects/{p['id']}").exists()
