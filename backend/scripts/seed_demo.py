"""Popula uma instância com dados de demonstração usando a API (usado no teste e2e do CI).

Use apenas com o simulador da OpenRouter (tests/fake_openrouter.py) — com a API real isto gera custos.

    python scripts/seed_demo.py --url http://127.0.0.1:8010 --user admin --password senha
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_pipeline import SCRIPT  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", required=True)
    ap.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args()
    c = httpx.Client(base_url=f"{args.url}/api", headers={"X-Requested-With": "dark-model"}, timeout=60)
    c.post("/auth/login", json={"username": args.user, "password": args.password}).raise_for_status()

    def wait(pid: int, label: str) -> dict:
        start = time.time()
        while time.time() - start < args.timeout:
            p = c.get(f"/projects/{pid}").json()
            if not p["active_jobs"]:
                print(f"{label}: ok ({time.time() - start:.1f}s)")
                return p
            time.sleep(1)
        raise SystemExit(f"{label}: tempo esgotado")

    ch = c.post("/channels", json={
        "name": "Archiwum Tajemnic", "language": "pl-PL", "country": "PL", "niche": "Tajemnice historyczne",
        "audience": "Dorośli 25–45 lat", "tone": "mroczny, spokojny", "visual_style": "cinematic, candlelight, film grain",
        "tts_model": "openai/gpt-4o-mini-tts", "tts_voice": "onyx",
    })
    ch.raise_for_status()
    cid = ch.json()["id"]
    pid = c.post("/projects", json={"channel_id": cid, "title": "Komora w Czechach", "script": SCRIPT}).json()["id"]
    for path, body, label in (
        ("analyze", None, "análise"), ("scenes/plan", {}, "cenas"), ("visuals", {"scope": "missing"}, "visuais"),
        ("narration", {}, "narração"), ("thumbnails", {}, "thumbnails"), ("metadata", None, "metadados"),
        ("export", {}, "exportação"),
    ):
        c.post(f"/projects/{pid}/{path}", json=body or {}).raise_for_status()
        p = wait(pid, label)
    failed = c.get("/jobs?status=failed").json()["jobs"]
    if failed:
        raise SystemExit(f"jobs com falha: {[(j['label'], j['error']) for j in failed]}")
    if not p["stages"]["render"]["last"]:
        raise SystemExit("o vídeo final não foi montado automaticamente depois da narração")
    print("stages:", {k: v for k, v in p["stages"].items() if k in ("visuals", "narration", "export", "render")})


if __name__ == "__main__":
    main()
