from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import get_current_user, require_admin
from ..models import Dataset, Recording, Speaker, User
from ..schemas import (
    LoginIn,
    PasswordChange,
    TokenOut,
    UserCreate,
    UserOut,
    UserPatch,
)
from ..services import auth as auth_svc

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(db: Session, user: User) -> UserOut:
    out = UserOut.model_validate(user)
    if user.dataset_id:
        ds = db.get(Dataset, user.dataset_id)
        out.dataset_name = ds.name if ds else None
    return out


def _ensure_speaker(db: Session, speaker_key: str, display_name: str) -> Speaker:
    speaker_key = speaker_key.strip()
    existing = db.query(Speaker).filter_by(speaker_key=speaker_key).first()
    if existing:
        return existing
    speaker = Speaker(speaker_key=speaker_key, display_name=display_name or speaker_key)
    db.add(speaker)
    db.flush()
    return speaker


# --- session ----------------------------------------------------------------
@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    user = db.query(User).filter(func.lower(User.username) == payload.username.strip().lower()).first()
    if not user or not auth_svc.verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Incorrect username or password")
    if not user.active:
        raise HTTPException(403, "This account has been deactivated")
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    token = auth_svc.create_token(user.id, auth_svc.get_auth_secret(settings))
    return TokenOut(token=token, user=user_out(db, user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_out(db, user)


@router.post("/change-password", response_model=UserOut)
def change_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not auth_svc.verify_password(payload.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = auth_svc.hash_password(payload.new_password)
    db.commit()
    return user_out(db, user)


# --- user management (admin) ------------------------------------------------
@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = db.query(User).order_by(User.role, User.id).all()
    return [user_out(db, u) for u in users]


@router.post("/users", response_model=UserOut)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if payload.role not in ("admin", "recorder"):
        raise HTTPException(400, "role must be 'admin' or 'recorder'")
    username = payload.username.strip()
    if db.query(User).filter(func.lower(User.username) == username.lower()).first():
        raise HTTPException(409, f"Username '{username}' is already taken")

    speaker_id = None
    if payload.role == "recorder":
        if not payload.dataset_id:
            raise HTTPException(400, "Recorder accounts must be assigned to a dataset")
        key = (payload.speaker_key or username).strip()
        speaker = _ensure_speaker(db, key, payload.display_name)
        speaker_id = speaker.id
        if payload.dataset_id and not db.get(Dataset, payload.dataset_id):
            raise HTTPException(404, "Assigned dataset not found")

    user = User(
        username=username,
        password_hash=auth_svc.hash_password(payload.password),
        role=payload.role,
        display_name=payload.display_name or username,
        speaker_id=speaker_id,
        dataset_id=payload.dataset_id if payload.role == "recorder" else None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user_out(db, user)


@router.patch("/users/{user_id}", response_model=UserOut)
def patch_user(
    user_id: int,
    payload: UserPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    data = payload.model_dump(exclude_unset=True)
    if "password" in data and data["password"]:
        user.password_hash = auth_svc.hash_password(data.pop("password"))
    else:
        data.pop("password", None)
    if "active" in data and not data["active"] and user.id == admin.id:
        raise HTTPException(400, "You cannot deactivate your own account")
    if "dataset_id" in data:
        if user.role == "recorder" and data["dataset_id"] is None:
            raise HTTPException(400, "Recorder accounts must be assigned to a dataset")
        if data["dataset_id"] is not None and not db.get(Dataset, data["dataset_id"]):
            raise HTTPException(404, "Assigned dataset not found")
    for key, value in data.items():
        setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user_out(db, user)


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Delete a login account without erasing historical voice identity."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(400, "You cannot delete your own account")
    if user.role == "admin":
        admin_count = db.query(func.count(User.id)).filter(User.role == "admin").scalar() or 0
        if admin_count <= 1:
            raise HTTPException(400, "The last administrator account cannot be deleted")

    username = user.username
    speaker_id = user.speaker_id
    db.delete(user)
    db.commit()
    return {
        "deleted": True,
        "user_id": user_id,
        "username": username,
        "speaker_id_preserved": speaker_id,
    }
