"""Login single-user: APP_USERNAME/APP_PASSWORD da Stack, sessão em cookie HttpOnly assinado."""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass

import jwt

from .config import get_settings

COOKIE_NAME = "dm_session"
ALGORITHM = "HS256"

# Bloqueio de força bruta: 5 falhas em 10 minutos por IP → espera crescente.
_MAX_FAILURES = 5
_WINDOW_SECONDS = 600
_failures: dict[str, list[float]] = {}
_lock = threading.Lock()


@dataclass
class LoginBlocked(Exception):
    retry_after: int


def _password_fingerprint() -> str:
    """Muda quando APP_USERNAME/APP_PASSWORD mudam: sessões antigas deixam de valer."""
    s = get_settings()
    raw = f"{s.app_username}\x00{s.app_password}".encode()
    return hmac.new(s.secret_key().encode(), raw, hashlib.sha256).hexdigest()[:24]


def check_rate_limit(ip: str) -> None:
    now = time.time()
    with _lock:
        recent = [t for t in _failures.get(ip, []) if now - t < _WINDOW_SECONDS]
        _failures[ip] = recent
        if len(recent) >= _MAX_FAILURES:
            excess = len(recent) - _MAX_FAILURES + 1
            wait = min(_WINDOW_SECONDS, 30 * (2 ** (excess - 1)))
            remaining = int(recent[-1] + wait - now)
            if remaining > 0:
                raise LoginBlocked(retry_after=remaining)


def register_failure(ip: str) -> None:
    with _lock:
        _failures.setdefault(ip, []).append(time.time())


def clear_failures(ip: str) -> None:
    with _lock:
        _failures.pop(ip, None)


def verify_credentials(username: str, password: str) -> bool:
    s = get_settings()
    if not s.credentials_configured:
        return False
    user_ok = hmac.compare_digest(username.strip().encode(), s.app_username.encode())
    pass_ok = hmac.compare_digest(password.encode(), s.app_password.encode())
    return user_ok and pass_ok


def create_session_token() -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": s.app_username,
        "iat": now,
        "exp": now + s.session_hours * 3600,
        "fp": _password_fingerprint(),
    }
    return jwt.encode(payload, s.secret_key(), algorithm=ALGORITHM)


def read_session_token(token: str | None) -> str | None:
    if not token:
        return None
    s = get_settings()
    try:
        payload = jwt.decode(token, s.secret_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("fp") != _password_fingerprint() or payload.get("sub") != s.app_username:
        return None
    return str(payload["sub"])
