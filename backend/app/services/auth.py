"""Authentication primitives — dependency-free password hashing and tokens.

Uses only the Python standard library so the app gains a real login layer
without adding packages (no bcrypt/passlib/jose build steps on Windows):

* Passwords are stored as PBKDF2-HMAC-SHA256 with a per-user random salt.
* Sessions are stateless signed tokens (a minimal JWT-like envelope) verified
  with an HMAC-SHA256 signature over ``base64url(payload)``.

The signing secret comes from ``AUTH_SECRET`` in the environment/.env; when it
is not set, a random secret is generated once and persisted to
``data/.auth_secret`` so tokens survive restarts on a single machine.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from ..config import Settings

_PBKDF2_ITERATIONS = 200_000
_TOKEN_TTL_HOURS = 24 * 7  # one week


# --- password hashing -------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(_PBKDF2_ITERATIONS),
            base64.b64encode(salt).decode(),
            base64.b64encode(dk).decode(),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, b64salt, b64hash = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(b64salt)
        expected = base64.b64decode(b64hash)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# --- token signing ----------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user_id: int, secret: str, ttl_hours: int = _TOKEN_TTL_HOURS) -> str:
    payload = {"uid": user_id, "exp": int(time.time()) + ttl_hours * 3600}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_token(token: str, secret: str) -> int | None:
    """Return the user id encoded in a valid, unexpired token, else None."""
    try:
        body, sig = token.split(".")
        expected = _b64e(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64d(body))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return int(payload["uid"])
    except Exception:
        return None


# --- signing secret ---------------------------------------------------------
_cached_secret: str | None = None


def get_auth_secret(settings: Settings) -> str:
    global _cached_secret
    if settings.auth_secret:
        return settings.auth_secret
    if _cached_secret:
        return _cached_secret
    secret_file: Path = settings.data_dir / ".auth_secret"
    if secret_file.exists():
        _cached_secret = secret_file.read_text(encoding="utf-8").strip()
    else:
        _cached_secret = secrets.token_hex(32)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(_cached_secret, encoding="utf-8")
    return _cached_secret
