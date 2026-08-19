"""Database-backed global transcript policy.

POLICY.md remains the shipped default and documentation source. Once an
administrator saves a policy in Settings, the database copy becomes the
effective policy and survives application deployments.
"""
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import AppSetting

POLICY_KEY = "global_text_policy"


def default_policy() -> str:
    project_root = Path(__file__).resolve().parents[3]
    for candidate in (project_root / "POLICY.md", Path("POLICY.md"), Path("../POLICY.md")):
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return "# Text policy\n\nNo default policy file was found."


def get_policy(db: Session) -> str:
    saved = db.get(AppSetting, POLICY_KEY)
    return saved.value if saved and saved.value.strip() else default_policy()


def save_policy(db: Session, text: str) -> str:
    value = text.strip()
    saved = db.get(AppSetting, POLICY_KEY)
    if saved:
        saved.value = value
    else:
        db.add(AppSetting(key=POLICY_KEY, value=value))
    db.commit()
    return value
