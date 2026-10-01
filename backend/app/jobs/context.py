"""Contexto entregue a cada handler: progresso, cancelamento, registro de consumo e jobs encadeados."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy.orm import Session

from .. import usage as usage_ledger
from ..db import session_scope
from ..models import Job
from ..providers.base import CanceledError, Usage
from . import queue

Handler = Callable[["JobContext"], dict[str, Any] | None]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


class JobContext:
    def __init__(self, job: Job):
        self.job_id = job.id
        self.kind = job.kind
        self.stage = job.stage
        self.payload: dict[str, Any] = dict(job.payload or {})
        self.project_id = job.project_id
        self.channel_id = job.channel_id
        self.scene_id = job.scene_id
        self.target_id = job.target_id
        self.parent_id = job.parent_id
        self.attempts = job.attempts
        self._last_beat = 0.0
        self._cancel = False

    # -------------------------------------------------------------- progresso / cancelamento

    def progress(self, value: float | None = None, message: str | None = None, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_beat < 0.8:
            return
        self._last_beat = now
        self._cancel = queue.heartbeat(self.job_id, value, message)
        if self._cancel:
            raise CanceledError("cancelado pelo usuário")

    def canceled(self) -> bool:
        now = time.monotonic()
        if now - self._last_beat >= 2.0:
            self._last_beat = now
            self._cancel = queue.heartbeat(self.job_id)
        return self._cancel

    @contextmanager
    def keepalive(self, every: float = 30.0) -> Iterator[None]:
        """Sinal de vida em segundo plano durante etapas longas sem progresso (ex.: um ffmpeg demorado).

        Sem isso, uma etapa de vários minutos parece um worker travado e a tarefa seria reenfileirada.
        """
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(every):
                try:
                    if queue.heartbeat(self.job_id):
                        self._cancel = True
                except Exception:  # noqa: BLE001 - o próximo sinal tenta de novo
                    logging.getLogger("dark_model.worker").exception("falha no sinal de vida do job %s", self.job_id)

        thread = threading.Thread(target=beat, name=f"keepalive-{self.job_id}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=5)

    def check_cancel(self) -> None:
        if self.canceled():
            raise CanceledError("cancelado pelo usuário")

    # -------------------------------------------------------------- consumo

    def record(self, db: Session, u: Usage, *, scene_id: int | None = None, stage: str | None = None,
               meta: dict[str, Any] | None = None) -> None:
        usage_ledger.record(
            db, u, stage=stage or self.stage, job_id=self.job_id, channel_id=self.channel_id,
            project_id=self.project_id, scene_id=scene_id if scene_id is not None else self.scene_id, meta=meta,
        )

    def record_now(self, u: Usage, **kw: Any) -> None:
        with session_scope() as db:
            self.record(db, u, **kw)

    # -------------------------------------------------------------- encadeamento

    def follow_up(self, db: Session, kind: str, **kw: Any) -> Job:
        kw.setdefault("project_id", self.project_id)
        kw.setdefault("channel_id", self.channel_id)
        kw.setdefault("parent_id", self.parent_id)
        return queue.enqueue(db, kind, **kw)
