"""Ponto de entrada do container: api | worker | all | migrate."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

from .config import BACKEND_DIR, get_settings

log = logging.getLogger("dark_model")


def ensure_database(url: str) -> None:
    """No PostgreSQL, cria o banco se ele ainda não existir (ex.: Postgres compartilhado da VPS)."""
    if not url.startswith("postgresql"):
        return
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError

    target = make_url(url)
    engine = create_engine(target, pool_pre_ping=True)
    try:
        with engine.connect():
            return
    except OperationalError as exc:
        if "does not exist" not in str(exc):
            raise
    finally:
        engine.dispose()
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            name = target.database or "darkmodel"
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name.replace(chr(34), "")}"'))
                log.info("banco %s criado", name)
    finally:
        admin.dispose()


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    logging.getLogger("alembic.runtime.plugins").setLevel(logging.WARNING)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().resolved_database_url.replace("%", "%%"))
    for attempt in range(30):
        try:
            ensure_database(get_settings().resolved_database_url)
            command.upgrade(cfg, "head")
            return
        except Exception as exc:  # noqa: BLE001 - banco ainda subindo
            if attempt == 29:
                raise
            log.warning("banco indisponível (%s); nova tentativa em 2s", exc)
            time.sleep(2)


def wait_for_schema(timeout: float = 300) -> None:
    from sqlalchemy import inspect

    from .db import get_engine

    start = time.monotonic()
    while True:
        try:
            if "jobs" in inspect(get_engine()).get_table_names():
                return
        except Exception as exc:  # noqa: BLE001
            log.info("aguardando banco: %s", exc)
        if time.monotonic() - start > timeout:
            raise SystemExit("o banco não ficou pronto a tempo (a API roda as migrações)")
        time.sleep(2)


def run_api(port: int) -> None:
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=port, workers=1, proxy_headers=True,
                forwarded_allow_ips="*", server_header=False, log_level=get_settings().log_level.lower())


def run_worker() -> None:
    from .jobs.worker import Worker

    wait_for_schema()
    worker = Worker()

    def stop(*_args) -> None:
        log.info("encerrando worker...")
        worker.stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker.run_forever()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dark-model")
    parser.add_argument("role", nargs="?", default=os.environ.get("ROLE", "api"),
                        choices=["api", "worker", "all", "migrate"])
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args(argv)
    logging.basicConfig(level=get_settings().log_level.upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.role == "migrate":
        migrate()
    elif args.role == "api":
        migrate()
        run_api(args.port)
    elif args.role == "all":
        os.environ["EMBEDDED_WORKER"] = "true"
        get_settings.cache_clear()
        migrate()
        run_api(args.port)
    else:
        run_worker()


if __name__ == "__main__":
    main()
