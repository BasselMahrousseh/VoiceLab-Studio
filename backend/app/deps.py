"""Shared FastAPI dependencies for authentication and authorization."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User
from .services import auth as auth_svc


def _user_from_token(token: str | None, db: Session) -> User:
    if not token:
        raise HTTPException(401, "Not authenticated")
    secret = auth_svc.get_auth_secret(get_settings())
    uid = auth_svc.decode_token(token, secret)
    if uid is None:
        raise HTTPException(401, "Invalid or expired session")
    user = db.get(User, uid)
    if not user or not user.active:
        raise HTTPException(401, "Account not found or deactivated")
    return user


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    return _user_from_token(_bearer(authorization), db)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user


# --- flexible variants for browser-initiated file requests ------------------
# <audio src> and <a href download> cannot set an Authorization header, so these
# accept the token via a `?token=` query parameter as a fallback.
def get_user_flexible(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> User:
    return _user_from_token(_bearer(authorization) or token, db)


def require_admin_flexible(user: User = Depends(get_user_flexible)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Admin access required")
    return user
