"""Admin analytics endpoints for recorder performance dashboards."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_admin
from ..models import User
from ..schemas import LeaderboardRowOut, PerformanceDashboardOut
from ..services import analytics as analytics_svc

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _parse_filters(
    date_from: datetime | None,
    date_to: datetime | None,
    dataset_id: int | None,
    language: str | None,
    dialect: str | None,
    human_status: str | None,
    session_id: int | None,
) -> analytics_svc.AnalyticsFilter:
    return analytics_svc.AnalyticsFilter(
        date_from=date_from,
        date_to=date_to,
        dataset_id=dataset_id,
        language=language,
        dialect=dialect,
        human_status=human_status,
        session_id=session_id,
    )


@router.get("/recorders", response_model=list[LeaderboardRowOut])
def list_recorder_performance(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    dataset_id: int | None = None,
    language: str | None = None,
    dialect: str | None = None,
    human_status: str | None = None,
    session_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """KPI summary for every recorder (leaderboard-ready)."""
    filters = _parse_filters(
        date_from, date_to, dataset_id, language, dialect, human_status, session_id
    )
    return analytics_svc.list_recorder_summaries(db, filters)


@router.get("/leaderboard", response_model=list[LeaderboardRowOut])
def team_leaderboard(
    metric: str = Query(
        "accepted",
        description="Sort key: accepted|acceptance_rate|speed|quality|hours|streak",
    ),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    dataset_id: int | None = None,
    language: str | None = None,
    dialect: str | None = None,
    limit: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    filters = _parse_filters(date_from, date_to, dataset_id, language, dialect, None, None)
    rows = analytics_svc.leaderboard(db, filters, limit=500)

    key_map = {
        "completed": lambda r: r.get("completed", 0),
        "accepted": lambda r: r["accepted"],
        "skipped": lambda r: r.get("skipped", 0),
        "remaining": lambda r: r.get("remaining", 0),
        "acceptance_rate": lambda r: r["acceptance_rate"],
        "speed": lambda r: -(r["avg_time_per_script_sec"] or 1e9),
        "quality": lambda r: r["avg_qc_score"] or 0,
        "hours": lambda r: r["hours_recorded"],
        "streak": lambda r: r["current_streak"],
    }
    key_fn = key_map.get(metric, key_map["completed"])
    rows.sort(key=key_fn, reverse=True)
    return rows[:limit]


@router.get("/recorders/{user_id}", response_model=PerformanceDashboardOut)
def recorder_performance_detail(
    user_id: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    dataset_id: int | None = None,
    language: str | None = None,
    dialect: str | None = None,
    human_status: str | None = None,
    session_id: int | None = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    """Full analytics payload for one recorder (admin view)."""
    user = db.get(User, user_id)
    if not user or user.role != "recorder":
        raise HTTPException(404, "Recorder not found")
    if not user.speaker_id:
        raise HTTPException(400, "Recorder has no linked speaker")
    filters = _parse_filters(
        date_from, date_to, dataset_id, language, dialect, human_status, session_id
    )
    try:
        return analytics_svc.build_dashboard(db, user, filters, include_charts=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
