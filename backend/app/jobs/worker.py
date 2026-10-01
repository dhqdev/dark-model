"""Worker: reserva jobs da fila e executa nos handlers, respeitando vagas por tipo (lane)."""

from __future__ import annotations

import logging
import os
import socket
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .. import usage as usage_ledger
from ..config import get_settings
from ..db import session_scope
from ..media import MediaError
from ..models import Job, JobStatus, WorkerHeartbeat, utcnow
from ..pipeline.common import StageError
from ..providers.base import CanceledError, ProviderError
from . import queue
from .context import HANDLERS, JobContext

log = logging.getLogger("dark_model.worker")


def _load_handlers() -> None:
    # importa os módulos do pipeline, que registram seus handlers
    from ..pipeline import handlers  # noqa: F401


def execute(job_id: int) -> str:
    """Executa um job já reservado. Retorna o status final."""
    _load_handlers()
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return "missing"
        ctx = JobContext(job)
        fn = HANDLERS.get(job.kind)
        kind = job.kind
        project_id = job.project_id
    status, result, error, retryable = JobStatus.SUCCEEDED.value, None, "", False
    try:
        if fn is None:
            raise RuntimeError(f"sem handler para o job '{kind}'")
        if kind not in queue.FREE_KINDS:
            with session_scope() as db:
                usage_ledger.check_budget(db, project_id)
        result = fn(ctx) or {}
    except CanceledError:
        status = JobStatus.CANCELED.value
    except (usage_ledger.BudgetExceeded, StageError) as exc:
        status, error = JobStatus.FAILED.value, str(exc)
    except ProviderError as exc:
        status, error, retryable = JobStatus.FAILED.value, str(exc), exc.retryable
    except MediaError as exc:
        status, error = JobStatus.FAILED.value, f"Erro de mídia: {exc}"
    except Exception as exc:  # noqa: BLE001
        log.error("job %s (%s) falhou:\n%s", job_id, kind, traceback.format_exc())
        status, error = JobStatus.FAILED.value, f"Erro interno: {exc}"
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is not None:
            queue.finish(db, job, status, result=result if status == JobStatus.SUCCEEDED.value else None,
                         error=error, retryable=retryable)
            status = job.status
    if error:
        log.warning("job %s (%s): %s", job_id, kind, error)
    return status


def run_until_idle(max_jobs: int = 10_000, lanes: set[str] | None = None) -> int:
    """Executa jobs em sequência até a fila esvaziar (testes / ferramentas)."""
    lanes = lanes or set(queue.LANES.values())
    worker_id = f"inline-{uuid.uuid4().hex[:6]}"
    done = 0
    while done < max_jobs:
        job_id = queue.claim(worker_id, lanes)
        if job_id is None:
            break
        execute(job_id)
        done += 1
    return done


class Worker:
    def __init__(self, worker_id: str | None = None):
        s = get_settings()
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:4]}"
        self.lanes = {k: v for k, v in s.lanes().items() if v > 0}
        self.poll = s.worker_poll_seconds
        self.stale_seconds = s.job_stale_seconds
        self.stop_event = threading.Event()
        self._active: dict[str, int] = {lane: 0 for lane in self.lanes}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_maintenance = 0.0
        self._last_reconcile = 0.0

    def start_background(self) -> None:
        self._thread = threading.Thread(target=self.run_forever, name="dark-model-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def _free_lanes(self) -> set[str]:
        with self._lock:
            return {lane for lane, cap in self.lanes.items() if self._active.get(lane, 0) < cap}

    def _done(self, lane: str) -> None:
        with self._lock:
            self._active[lane] = max(0, self._active.get(lane, 0) - 1)

    def _run(self, job_id: int, lane: str) -> None:
        try:
            execute(job_id)
        finally:
            self._done(lane)

    def _maintenance(self) -> None:
        import time

        now = time.monotonic()
        if now - self._last_maintenance < 20:
            return
        self._last_maintenance = now
        try:
            with session_scope() as db:
                hb = db.get(WorkerHeartbeat, self.worker_id)
                info: dict[str, Any] = {"lanes": self.lanes, "active": dict(self._active)}
                if hb is None:
                    db.add(WorkerHeartbeat(worker_id=self.worker_id, hostname=socket.gethostname(), info=info))
                else:
                    hb.seen_at = utcnow()
                    hb.info = info
                recovered = queue.recover_stale(db, self.stale_seconds)
                if recovered:
                    log.warning("%s jobs travados foram recuperados", recovered)
            if now - self._last_reconcile > 60 and get_settings().openrouter_configured:
                self._last_reconcile = now
                from ..providers.registry import openrouter_client

                with session_scope() as db:
                    fixed = usage_ledger.reconcile_pending(db, openrouter_client())
                if fixed:
                    log.info("%s custos pendentes confirmados pela OpenRouter", fixed)
        except Exception:  # noqa: BLE001
            log.exception("falha na manutenção do worker")

    def run_forever(self) -> None:
        _load_handlers()
        log.info("worker %s iniciado; vagas: %s", self.worker_id, self.lanes)
        with ThreadPoolExecutor(max_workers=max(1, sum(self.lanes.values())), thread_name_prefix="job") as pool:
            while not self.stop_event.is_set():
                self._maintenance()
                free = self._free_lanes()
                job_id = None
                if free:
                    try:
                        job_id = queue.claim(self.worker_id, free)
                    except Exception:  # noqa: BLE001 - banco indisponível momentaneamente
                        log.exception("falha ao buscar job")
                if job_id is None:
                    self.stop_event.wait(self.poll)
                    continue
                with session_scope() as db:
                    lane = db.get(Job, job_id).lane
                with self._lock:
                    self._active[lane] = self._active.get(lane, 0) + 1
                pool.submit(self._run, job_id, lane)
        log.info("worker %s finalizado", self.worker_id)
