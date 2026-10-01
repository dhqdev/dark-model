"""Configuração lida das variáveis de ambiente (Stack do Portainer / .env)."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- acesso (single-user) ---
    app_username: str = ""
    app_password: str = ""
    # Assina o cookie de sessão. Se vazio, é gerado e salvo em DATA_DIR/secret.key.
    app_secret_key: str = ""
    cookie_secure: bool = False
    session_hours: int = 72

    # --- OpenRouter ---
    openrouter_api_key: str = ""
    # Opcional: chave de gerenciamento, necessária para ler o saldo em /credits.
    openrouter_management_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # URL pública da plataforma (enviada como HTTP-Referer para a OpenRouter).
    app_public_url: str = ""
    app_name: str = "Dark Model"

    # --- infraestrutura ---
    app_env: str = "development"
    database_url: str = ""
    # Alternativa ao DATABASE_URL (a senha pode ter qualquer caractere)
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_user: str = "dark"
    postgres_password: str = ""
    postgres_db: str = "darkmodel"
    data_dir: Path = Field(default=BACKEND_DIR / "data")
    frontend_dist: Path | None = None
    log_level: str = "INFO"
    # Worker dentro do processo da API (útil para instalação mínima, sem container de worker).
    embedded_worker: bool = False
    # Vagas simultâneas por tipo de tarefa: llm, image, tts, video, cpu (ffmpeg).
    worker_lanes: str = "llm=2,image=4,tts=3,video=2,cpu=1"
    worker_poll_seconds: float = 1.0
    # Quanto tempo sem sinal de vida até uma tarefa "rodando" ser considerada travada.
    job_stale_seconds: int = 300
    catalog_ttl_minutes: int = 360
    # --- moeda: custos e tetos por vídeo em reais ---
    # Cotação do dólar usada quando a cotação ao vivo não está disponível (ou sempre, com FX_AUTO=false).
    usd_brl: float = 5.5
    fx_auto: bool = True
    # Clipes de movimento (IMAGE + MOTION) renderizados localmente
    motion_size: str = "1920x1080"
    motion_fps: int = 30
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            url = self.database_url
            # aceita o formato curto "postgresql://" e usa o driver psycopg 3
            if url.startswith("postgres://"):
                url = "postgresql+psycopg://" + url[len("postgres://"):]
            elif url.startswith("postgresql://"):
                url = "postgresql+psycopg://" + url[len("postgresql://"):]
            return url
        if self.postgres_host:
            from urllib.parse import quote_plus

            return (f"postgresql+psycopg://{quote_plus(self.postgres_user)}:{quote_plus(self.postgres_password)}"
                    f"@{self.postgres_host}:{self.postgres_port}/{quote_plus(self.postgres_db)}")
        return f"sqlite:///{self.data_dir / 'dark-model.db'}"

    @property
    def credentials_configured(self) -> bool:
        return bool(self.app_username and self.app_password)

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key)

    def motion_dims(self) -> tuple[int, int]:
        try:
            w, h = (int(x) for x in self.motion_size.lower().split("x", 1))
            return max(64, w), max(64, h)
        except ValueError:
            return 1920, 1080

    def lanes(self) -> dict[str, int]:
        lanes = {"llm": 2, "image": 4, "tts": 3, "video": 2, "cpu": 1}
        for part in self.worker_lanes.split(","):
            if "=" not in part:
                continue
            name, _, value = part.partition("=")
            try:
                lanes[name.strip()] = max(0, int(value))
            except ValueError:
                continue
        return lanes

    def secret_key(self) -> str:
        if self.app_secret_key:
            return self.app_secret_key
        path = self.data_dir / "secret.key"
        if path.exists():
            return path.read_text().strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key = secrets.token_urlsafe(48)
        path.write_text(key)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return key


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
