"""Aggregated recorder-performance analytics from existing Recording / Session data.

All metrics are derived from stored rows (no mock data). ASR confidence uses
``1 - asr_wer`` when ASR has been run; otherwise it is omitted (recorder flow
does not auto-verify).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any, Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from ..models import Recording, RecordingSession, Script, User

QC_SCORE = {"passed": 100.0, "warning": 70.0, "failed": 30.0}


@dataclass
class AnalyticsFilter:
    date_from: datetime | None = None
    date_to: datetime | None = None
    dataset_id: int | None = None
    language: str | None = None
    dialect: str | None = None
    human_status: str | None = None
    session_id: int | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _day(dt: datetime) -> date:
    return _as_utc(dt).date()  # type: ignore[union-attr]


def _safe_mean(values: Iterable[float | None]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    return round(mean(nums), 3) if nums else None


def _pct(part: int, whole: int) -> float:
    return round((part / whole) * 100.0, 1) if whole else 0.0


def _trend(current: float | None, previous: float | None) -> dict[str, Any]:
    if current is None or previous is None:
        return {"current": current, "previous": previous, "delta": None, "direction": "stable"}
    delta = round(current - previous, 2)
    if abs(delta) < 0.5:
        direction = "stable"
    elif delta > 0:
        direction = "improving"
    else:
        direction = "declining"
    return {"current": current, "previous": previous, "delta": delta, "direction": direction}


def _metric(rec: Recording, key: str) -> float | None:
    raw = (rec.qc_metrics or {}).get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _qc_score(rec: Recording) -> float:
    return QC_SCORE.get(rec.qc_status, 50.0)


def _asr_confidence(rec: Recording) -> float | None:
    if rec.asr_status in (None, "not_run", "error"):
        return None
    if rec.asr_wer is not None:
        return round(max(0.0, min(1.0, 1.0 - float(rec.asr_wer))) * 100.0, 1)
    if rec.asr_cer is not None:
        return round(max(0.0, min(1.0, 1.0 - float(rec.asr_cer))) * 100.0, 1)
    if rec.asr_status == "match":
        return 98.0
    if rec.asr_status == "minor_mismatch":
        return 80.0
    if rec.asr_status == "major_mismatch":
        return 50.0
    return None


def _recordings_query(db: Session, speaker_id: int, filters: AnalyticsFilter):
    q = db.query(Recording).filter(Recording.speaker_id == speaker_id)
    if filters.date_from:
        q = q.filter(Recording.created_at >= filters.date_from)
    if filters.date_to:
        q = q.filter(Recording.created_at <= filters.date_to)
    if filters.session_id:
        q = q.filter(Recording.session_id == filters.session_id)
    if filters.human_status:
        q = q.filter(Recording.human_status == filters.human_status)
    if filters.dataset_id or filters.language or filters.dialect:
        q = q.join(Script, Script.id == Recording.script_pk)
        if filters.dataset_id:
            q = q.filter(Script.dataset_id == filters.dataset_id)
        if filters.language:
            q = q.filter(Script.language == filters.language)
        if filters.dialect:
            q = q.filter(Script.dialect == filters.dialect)
    return q


def load_recordings(
    db: Session, speaker_id: int, filters: AnalyticsFilter | None = None
) -> list[Recording]:
    filters = filters or AnalyticsFilter()
    return (
        _recordings_query(db, speaker_id, filters)
        .options(joinedload(Recording.script))
        .order_by(Recording.created_at.asc())
        .all()
    )


def progress_for_user(db: Session, user: User) -> dict[str, Any]:
    from ..models import ScriptSkip

    if not user.dataset_id or not user.speaker_id:
        return {
            "assigned": 0,
            "completed": 0,
            "remaining": 0,
            "skipped": 0,
            "percent": 0.0,
            "estimated_remaining_sec": None,
        }
    total = (
        db.query(func.count(Script.id))
        .filter(
            Script.dataset_id == user.dataset_id,
            Script.active.is_(True),
            Script.status.notin_(["flagged", "retired"]),
        )
        .scalar()
        or 0
    )
    accepted_ids = (
        db.query(Recording.script_pk)
        .filter(Recording.speaker_id == user.speaker_id, Recording.human_status == "accepted")
        .distinct()
    )
    done = (
        db.query(func.count(Script.id))
        .filter(
            Script.dataset_id == user.dataset_id,
            Script.active.is_(True),
            Script.status.notin_(["flagged", "retired"]),
            Script.id.in_(accepted_ids),
        )
        .scalar()
        or 0
    )
    skipped = (
        db.query(func.count(ScriptSkip.id))
        .filter(ScriptSkip.speaker_id == user.speaker_id)
        .scalar()
        or 0
    )
    remaining = max(total - done, 0)
    avg_dur = (
        db.query(func.avg(Recording.duration_sec))
        .filter(Recording.speaker_id == user.speaker_id, Recording.human_status == "accepted")
        .scalar()
    )
    eta = round(float(avg_dur) * remaining) if avg_dur and remaining else None
    return {
        "assigned": total,
        "completed": done,
        "remaining": remaining,
        "skipped": int(skipped),
        "percent": _pct(done, total),
        "estimated_remaining_sec": eta,
    }


def _status_counts(recs: list[Recording]) -> dict[str, int]:
    c = Counter(r.human_status for r in recs)
    return {
        "accepted": c.get("accepted", 0),
        "pending": c.get("pending", 0),
        "rejected": c.get("rejected", 0),
        "total": len(recs),
    }


def _quality_block(recs: list[Recording]) -> dict[str, Any]:
    counts = _status_counts(recs)
    reviewed = counts["accepted"] + counts["rejected"]
    multi_take_accepted = sum(
        1 for r in recs if r.human_status == "accepted" and (r.take_number or 1) > 1
    )
    accepted = counts["accepted"]
    return {
        **counts,
        "acceptance_rate": _pct(counts["accepted"], reviewed),
        "rerecord_rate": _pct(multi_take_accepted, accepted),
    }


def _streaks(accepted_days: list[date]) -> dict[str, Any]:
    uniq = sorted(set(accepted_days))
    if not uniq:
        return {
            "current_streak": 0,
            "longest_streak": 0,
            "recordings_today": 0,
            "avg_per_day": 0.0,
        }
    today = _utcnow().date()
    day_counts = Counter(accepted_days)

    longest = 1
    run = 1
    for i in range(1, len(uniq)):
        if (uniq[i] - uniq[i - 1]).days == 1:
            run += 1
            longest = max(longest, run)
        else:
            run = 1

    current = 0
    cursor = today
    # Allow yesterday if nothing yet today (still "active" streak)
    if cursor not in day_counts and (cursor - timedelta(days=1)) in day_counts:
        cursor = cursor - timedelta(days=1)
    while cursor in day_counts:
        current += 1
        cursor -= timedelta(days=1)

    span_days = max((uniq[-1] - uniq[0]).days + 1, 1)
    return {
        "current_streak": current,
        "longest_streak": longest,
        "recordings_today": day_counts.get(today, 0),
        "avg_per_day": round(len(accepted_days) / span_days, 2),
    }


def _activity_block(recs: list[Recording]) -> dict[str, Any]:
    now = _utcnow()
    today = now.date()
    yesterday = today - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    accepted = [r for r in recs if r.human_status == "accepted" and r.created_at]
    by_day = [_day(r.created_at) for r in accepted]

    def count_on(pred) -> int:
        return sum(1 for d in by_day if pred(d))

    streaks = _streaks(by_day)
    return {
        "today": count_on(lambda d: d == today),
        "yesterday": count_on(lambda d: d == yesterday),
        "this_week": count_on(lambda d: d >= week_start),
        "this_month": count_on(lambda d: d >= month_start),
        "recording_streak": streaks["current_streak"],
        "longest_streak": streaks["longest_streak"],
        "avg_recordings_per_day": streaks["avg_per_day"],
        "recordings_today": streaks["recordings_today"],
    }


def _productivity_block(recs: list[Recording]) -> dict[str, Any]:
    accepted = [r for r in recs if r.human_status == "accepted"]
    durations = [r.duration_sec for r in accepted if r.duration_sec]
    qc_scores = [_qc_score(r) for r in accepted]
    asr_conf = [_asr_confidence(r) for r in accepted]
    # Approximate time-per-script from gaps between consecutive accepts (cap 30m)
    gaps: list[float] = []
    ordered = sorted(accepted, key=lambda r: r.created_at or _utcnow())
    for a, b in zip(ordered, ordered[1:]):
        if not a.created_at or not b.created_at:
            continue
        gap = (_as_utc(b.created_at) - _as_utc(a.created_at)).total_seconds()  # type: ignore[operator]
        if 0 < gap <= 1800:
            gaps.append(gap)
    return {
        "avg_recording_duration_sec": _safe_mean(durations),
        "avg_qc_score": _safe_mean(qc_scores),
        "avg_asr_confidence": _safe_mean(asr_conf),
        "avg_time_per_script_sec": _safe_mean(gaps),
        "fastest_recording_sec": round(min(durations), 3) if durations else None,
        "longest_recording_sec": round(max(durations), 3) if durations else None,
        "hours_recorded": round(sum(durations) / 3600.0, 3) if durations else 0.0,
        "total_speech_duration_sec": round(sum(durations), 2) if durations else 0.0,
    }


def _audio_quality_block(recs: list[Recording]) -> dict[str, Any]:
    focus = [r for r in recs if r.human_status in ("accepted", "pending")]
    if not focus:
        focus = recs
    clip_total = 0
    for r in focus:
        c = _metric(r, "clip_count")
        if c:
            clip_total += int(c)
    silence_vals = []
    for r in focus:
        lead = _metric(r, "leading_silence_sec") or 0.0
        trail = _metric(r, "trailing_silence_sec") or 0.0
        dur = r.duration_sec or 0.0
        if dur > 0:
            silence_vals.append(((lead + trail) / dur) * 100.0)
    speech_ratios = [_metric(r, "speech_ratio") for r in focus]
    snrs = [_metric(r, "snr_db") for r in focus]
    return {
        "avg_loudness_lufs": _safe_mean([_metric(r, "lufs") for r in focus]),
        "avg_peak_dbfs": _safe_mean([_metric(r, "peak_dbfs") for r in focus]),
        "avg_noise_floor_dbfs": _safe_mean([_metric(r, "noise_floor_dbfs") for r in focus]),
        "avg_rms_dbfs": _safe_mean([_metric(r, "rms_dbfs") for r in focus]),
        "clipping_count": clip_total,
        "avg_silence_pct": _safe_mean(silence_vals),
        "avg_snr_db": _safe_mean(snrs),
        "avg_speech_ratio": _safe_mean(speech_ratios),
        "microphone_consistency": _mic_consistency(focus),
        "signal_quality": _signal_quality(focus),
    }


def _mic_consistency(recs: list[Recording]) -> str:
    peaks = [_metric(r, "peak_dbfs") for r in recs]
    peaks = [p for p in peaks if p is not None]
    if len(peaks) < 3:
        return "insufficient_data"
    avg = mean(peaks)
    variance = mean((p - avg) ** 2 for p in peaks)
    if variance < 4:
        return "excellent"
    if variance < 12:
        return "good"
    if variance < 25:
        return "fair"
    return "needs_adjustment"


def _signal_quality(recs: list[Recording]) -> str:
    snrs = [_metric(r, "snr_db") for r in recs]
    snrs = [s for s in snrs if s is not None]
    if not snrs:
        return "unknown"
    avg = mean(snrs)
    if avg >= 25:
        return "excellent"
    if avg >= 18:
        return "good"
    if avg >= 12:
        return "fair"
    return "poor"


def _insights(recs: list[Recording], quality: dict, audio: dict, activity: dict) -> list[dict]:
    insights: list[dict] = []
    rate = quality.get("acceptance_rate") or 0
    if rate >= 95 and quality["accepted"] >= 10:
        insights.append(
            {"code": "great_consistency", "level": "success", "message": "Great consistency — high acceptance rate"}
        )
    elif rate < 80 and quality["accepted"] + quality["rejected"] >= 10:
        insights.append(
            {"code": "high_rejection", "level": "warn", "message": "High rejection rate — review delivery and mic setup"}
        )

    if quality.get("rerecord_rate", 0) >= 25 and quality["accepted"] >= 8:
        insights.append(
            {
                "code": "many_rerecords",
                "level": "warn",
                "message": "Many clips need re-recording — slow down and watch the level meter",
            }
        )

    quiet_codes = {"quiet", "low_snr", "snr", "noise_floor"}
    quiet_hits = sum(
        1
        for r in recs
        for issue in (r.qc_issues or [])
        if isinstance(issue, dict) and issue.get("code") in quiet_codes
    )
    if quiet_hits >= max(3, len(recs) // 10):
        insights.append(
            {"code": "speaking_quietly", "level": "warn", "message": "Speaking too quietly or noise floor is high"}
        )

    clip_hits = sum(
        1
        for r in recs
        for issue in (r.qc_issues or [])
        if isinstance(issue, dict) and str(issue.get("code", "")).startswith("clip")
    )
    if clip_hits >= 3:
        insights.append(
            {"code": "mic_gain", "level": "warn", "message": "Needs microphone adjustment — clipping detected often"}
        )
    elif audio.get("avg_loudness_lufs") is not None and audio["avg_loudness_lufs"] < -28:
        insights.append(
            {"code": "gain_up", "level": "info", "message": "Recommend microphone gain +3 dB"}
        )

    if audio.get("microphone_consistency") == "excellent":
        insights.append(
            {"code": "mic_consistent", "level": "success", "message": "Excellent microphone consistency"}
        )

    asr_match = sum(1 for r in recs if r.human_status == "accepted" and r.asr_status == "match")
    asr_total = sum(1 for r in recs if r.human_status == "accepted" and r.asr_status not in ("not_run", "error", None))
    if asr_total >= 5 and (asr_match / asr_total) >= 0.9:
        insights.append(
            {"code": "pronunciation", "level": "success", "message": "Excellent pronunciation (ASR match rate)"}
        )

    prod = _productivity_block(recs)
    if (prod.get("avg_time_per_script_sec") or 999) < 25 and quality["accepted"] >= 15:
        insights.append(
            {"code": "fast_recorder", "level": "success", "message": "Excellent recording speed"}
        )

    if activity.get("recording_streak", 0) >= 3:
        insights.append(
            {
                "code": "streak",
                "level": "success",
                "message": f"{activity['recording_streak']}-day recording streak — keep it going",
            }
        )

    # Domain strength
    domain_ok: Counter[str] = Counter()
    domain_all: Counter[str] = Counter()
    for r in recs:
        if not r.script:
            continue
        domain_all[r.script.domain] += 1
        if r.human_status == "accepted":
            domain_ok[r.script.domain] += 1
    best = None
    best_rate = 0.0
    for domain, n in domain_all.items():
        if n < 5:
            continue
        rate_d = domain_ok[domain] / n
        if rate_d > best_rate:
            best_rate = rate_d
            best = domain
    if best and best_rate >= 0.9:
        label = best.replace("_", " ").title()
        insights.append(
            {
                "code": "domain_best",
                "level": "info",
                "message": f"Performs best on {label} scripts",
            }
        )

    # Long-sentence rejections
    long_rej = sum(
        1
        for r in recs
        if r.human_status == "rejected"
        and r.script
        and (r.script.length_bucket == "long" or r.script.word_count >= 18)
    )
    long_tot = sum(
        1
        for r in recs
        if r.script and (r.script.length_bucket == "long" or r.script.word_count >= 18)
    )
    if long_tot >= 5 and long_rej / long_tot >= 0.3:
        insights.append(
            {
                "code": "long_sentences",
                "level": "info",
                "message": "Most rejections happen on longer sentences",
            }
        )

    if not insights:
        insights.append(
            {"code": "keep_going", "level": "info", "message": "Keep recording — insights appear as more takes accumulate"}
        )
    return insights[:8]


def _achievements(recs: list[Recording], quality: dict, activity: dict, productivity: dict) -> list[dict]:
    accepted = quality["accepted"]
    badges: list[dict] = []

    def add(code: str, icon: str, title: str, earned: bool, detail: str = ""):
        badges.append({"code": code, "icon": icon, "title": title, "earned": earned, "detail": detail})

    add("rec_100", "🥇", "100 recordings completed", accepted >= 100, f"{accepted} accepted")
    add("rec_500", "⭐", "500 accepted clips", accepted >= 500, f"{accepted} accepted")
    add("streak_7", "🔥", "7-day streak", activity.get("recording_streak", 0) >= 7 or activity.get("longest_streak", 0) >= 7)
    add(
        "accept_98",
        "🎯",
        "98% acceptance rate",
        (quality.get("acceptance_rate") or 0) >= 98 and (quality["accepted"] + quality["rejected"]) >= 20,
        f"{quality.get('acceptance_rate')}%",
    )
    add(
        "fast",
        "⚡",
        "Fast recorder",
        (productivity.get("avg_time_per_script_sec") or 999) < 25 and accepted >= 20,
    )
    add(
        "quality",
        "💎",
        "Quality master",
        (productivity.get("avg_qc_score") or 0) >= 90 and accepted >= 25,
        f"QC {productivity.get('avg_qc_score')}",
    )
    add("first_10", "🎙️", "First 10 clips", accepted >= 10, f"{accepted} accepted")
    add("hours_1", "⏱️", "1 hour contributed", (productivity.get("hours_recorded") or 0) >= 1.0)
    return badges


def _session_summary(db: Session, session: RecordingSession | None, recs: list[Recording] | None = None) -> dict[str, Any] | None:
    if not session:
        return None
    if recs is None:
        recs = (
            db.query(Recording)
            .options(joinedload(Recording.script))
            .filter(Recording.session_id == session.id)
            .all()
        )
    else:
        recs = [r for r in recs if r.session_id == session.id]

    started = _as_utc(session.started_at)
    ended = _as_utc(session.ended_at) or _utcnow()
    duration = max((ended - started).total_seconds(), 0) if started else 0
    counts = _status_counts(recs)
    accepted = [r for r in recs if r.human_status == "accepted"]
    words = sum((r.script.word_count if r.script else 0) for r in accepted)
    chars = sum((r.script.char_count if r.script else 0) for r in accepted)
    clip_events = 0
    for r in recs:
        c = _metric(r, "clip_count")
        if c:
            clip_events += int(c)
    return {
        "session_id": session.id,
        "started_at": session.started_at,
        "ended_at": session.ended_at,
        "session_duration_sec": round(duration, 1),
        "recorded_clips": len(recs),
        "accepted_clips": counts["accepted"],
        "pending_clips": counts["pending"],
        "rejected_clips": counts["rejected"],
        "avg_recording_time_sec": _safe_mean([r.duration_sec for r in accepted]),
        "avg_loudness_lufs": _safe_mean([_metric(r, "lufs") for r in recs]),
        "clipping_events": clip_events,
        "words_recorded": words,
        "characters_recorded": chars,
        "estimated_speech_duration_sec": round(sum(r.duration_sec or 0 for r in accepted), 2),
        "room_tone_dbfs": session.room_tone_dbfs,
        "room_tone_status": session.room_tone_status,
        "device_info": session.device_info or {},
    }


def _charts(recs: list[Recording]) -> dict[str, Any]:
    accepted = [r for r in recs if r.human_status == "accepted" and r.created_at]
    daily: Counter[str] = Counter()
    weekly: Counter[str] = Counter()
    qc_by_day: dict[str, list[float]] = defaultdict(list)
    hour_heat: Counter[tuple[int, int]] = Counter()
    durations: list[float] = []
    domains: Counter[str] = Counter()
    calendar: Counter[str] = Counter()

    for r in accepted:
        dt = _as_utc(r.created_at)
        if not dt:
            continue
        dkey = dt.date().isoformat()
        daily[dkey] += 1
        calendar[dkey] += 1
        iso = dt.isocalendar()
        weekly[f"{iso.year}-W{iso.week:02d}"] += 1
        qc_by_day[dkey].append(_qc_score(r))
        hour_heat[(dt.weekday(), dt.hour)] += 1
        if r.duration_sec:
            durations.append(r.duration_sec)
        if r.script:
            domains[r.script.domain or "general"] += 1

    # Duration histogram buckets (seconds)
    buckets = [(0, 2), (2, 4), (4, 6), (6, 8), (8, 12), (12, 20), (20, 1e9)]
    hist = []
    for lo, hi in buckets:
        label = f"{lo}-{int(hi)}s" if hi < 1e8 else f"{lo}+s"
        hist.append({"bucket": label, "count": sum(1 for d in durations if lo <= d < hi)})

    status = _status_counts(recs)
    return {
        "daily_recordings": [{"date": k, "count": daily[k]} for k in sorted(daily)],
        "weekly_productivity": [{"week": k, "count": weekly[k]} for k in sorted(weekly)],
        "accepted_vs_rejected": {
            "accepted": status["accepted"],
            "rejected": status["rejected"],
            "pending": status["pending"],
        },
        "qc_score_over_time": [
            {"date": k, "avg_qc_score": round(mean(v), 1)} for k, v in sorted(qc_by_day.items())
        ],
        "hour_heatmap": [
            {"weekday": dow, "hour": hour, "count": count}
            for (dow, hour), count in sorted(hour_heat.items())
        ],
        "duration_histogram": hist,
        "dataset_contribution": [
            {"domain": k, "count": domains[k]} for k in sorted(domains, key=domains.get, reverse=True)
        ],
        "activity_calendar": [{"date": k, "count": calendar[k]} for k in sorted(calendar)],
    }


def _trends(recs: list[Recording]) -> dict[str, Any]:
    now = _utcnow()
    week_ago = now - timedelta(days=7)
    two_weeks = now - timedelta(days=14)

    def slice_recs(start: datetime, end: datetime) -> list[Recording]:
        out = []
        for r in recs:
            dt = _as_utc(r.created_at)
            if dt and start <= dt < end:
                out.append(r)
        return out

    cur = slice_recs(week_ago, now)
    prev = slice_recs(two_weeks, week_ago)

    def accept_rate(rs: list[Recording]) -> float | None:
        a = sum(1 for r in rs if r.human_status == "accepted")
        rj = sum(1 for r in rs if r.human_status == "rejected")
        if a + rj == 0:
            return None
        return _pct(a, a + rj)

    def speed(rs: list[Recording]) -> float | None:
        accepted = sorted(
            [r for r in rs if r.human_status == "accepted" and r.created_at],
            key=lambda r: r.created_at,
        )
        gaps = []
        for a, b in zip(accepted, accepted[1:]):
            gap = (_as_utc(b.created_at) - _as_utc(a.created_at)).total_seconds()  # type: ignore[operator]
            if 0 < gap <= 1800:
                gaps.append(gap)
        # Invert: lower gap = faster → report scripts/hour
        if not gaps:
            return None
        return round(3600.0 / mean(gaps), 2)

    return {
        "acceptance_rate": _trend(accept_rate(cur), accept_rate(prev)),
        "speed_scripts_per_hour": _trend(speed(cur), speed(prev)),
        "qc_score": _trend(
            _safe_mean([_qc_score(r) for r in cur if r.human_status == "accepted"]),
            _safe_mean([_qc_score(r) for r in prev if r.human_status == "accepted"]),
        ),
        "asr_confidence": _trend(
            _safe_mean([_asr_confidence(r) for r in cur if r.human_status == "accepted"]),
            _safe_mean([_asr_confidence(r) for r in prev if r.human_status == "accepted"]),
        ),
    }


def _ai_insights(trends: dict, quality: dict, insights: list[dict]) -> list[str]:
    lines: list[str] = []
    ar = trends.get("acceptance_rate") or {}
    if ar.get("delta") is not None and ar["delta"] != 0:
        verb = "increased" if ar["delta"] > 0 else "decreased"
        lines.append(f"Acceptance rate {verb} by {abs(ar['delta'])}% this week.")
    for item in insights:
        if item["level"] in ("warn", "success", "info"):
            lines.append(item["message"])
    if quality.get("pending", 0) > 0:
        lines.append(f"{quality['pending']} clip(s) still pending review.")
    # Dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out[:6]


def _profile(db: Session, user: User) -> dict[str, Any]:
    session = None
    if user.speaker_id:
        session = (
            db.query(RecordingSession)
            .filter(RecordingSession.speaker_id == user.speaker_id)
            .order_by(RecordingSession.id.desc())
            .first()
        )
    last_rec = None
    if user.speaker_id:
        last_rec = (
            db.query(Recording)
            .filter(Recording.speaker_id == user.speaker_id)
            .order_by(Recording.created_at.desc())
            .first()
        )
    device = (session.device_info if session else {}) or {}
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "active": user.active,
        "joined_at": user.created_at,
        "last_login_at": user.last_login_at,
        "last_active_at": last_rec.created_at if last_rec else user.last_login_at,
        "speaker_id": user.speaker_id,
        "speaker_key": user.speaker.speaker_key if user.speaker else None,
        "dataset_id": user.dataset_id,
        "dataset_name": user.dataset.name if user.dataset else None,
        "dataset_language": user.dataset.language if user.dataset else None,
        "dataset_dialect": user.dataset.dialect if user.dataset else None,
        "status": "active" if user.active else "inactive",
        "recording_device": device.get("deviceLabel") or device.get("device_label") or device.get("deviceId"),
        "browser": device.get("browser") or device.get("userAgent"),
        "microphone": device.get("microphone") or device.get("deviceLabel"),
        "device_info": device,
    }


def build_dashboard(
    db: Session,
    user: User,
    filters: AnalyticsFilter | None = None,
    include_charts: bool = True,
) -> dict[str, Any]:
    filters = filters or AnalyticsFilter()
    if not user.speaker_id:
        raise ValueError("User has no linked speaker")

    # Progress is always against assigned dataset (not date-filtered)
    progress = progress_for_user(db, user)
    recs = load_recordings(db, user.speaker_id, filters)
    quality = _quality_block(recs)
    activity = _activity_block(recs)
    productivity = _productivity_block(recs)
    audio = _audio_quality_block(recs)
    insights = _insights(recs, quality, audio, activity)
    achievements = _achievements(recs, quality, activity, productivity)
    trends = _trends(recs)
    charts = _charts(recs) if include_charts else {}

    open_session = (
        db.query(RecordingSession)
        .filter(
            RecordingSession.speaker_id == user.speaker_id,
            RecordingSession.ended_at.is_(None),
        )
        .order_by(RecordingSession.id.desc())
        .first()
    )
    session_summary = _session_summary(db, open_session, recs)

    kpis = {
        "total_recordings": quality["total"],
        "accepted": quality["accepted"],
        "rejected": quality["rejected"],
        "pending": quality["pending"],
        "skipped": progress.get("skipped", 0),
        "completed": progress.get("completed", 0),
        "remaining": progress.get("remaining", 0),
        "assigned": progress.get("assigned", 0),
        "acceptance_pct": quality["acceptance_rate"],
        "avg_recording_time_sec": productivity["avg_recording_duration_sec"],
        "hours_recorded": productivity["hours_recorded"],
    }

    return {
        "profile": _profile(db, user),
        "progress": progress,
        "quality": quality,
        "activity": activity,
        "productivity": productivity,
        "audio_quality": audio,
        "insights": insights,
        "ai_insights": _ai_insights(trends, quality, insights),
        "achievements": achievements,
        "session_summary": session_summary,
        "kpis": kpis,
        "trends": trends,
        "charts": charts,
        "filters": {
            "date_from": filters.date_from,
            "date_to": filters.date_to,
            "dataset_id": filters.dataset_id,
            "language": filters.language,
            "dialect": filters.dialect,
            "human_status": filters.human_status,
            "session_id": filters.session_id,
        },
    }


def leaderboard(db: Session, filters: AnalyticsFilter | None = None, limit: int = 50) -> list[dict]:
    filters = filters or AnalyticsFilter()
    recorders = (
        db.query(User)
        .filter(User.role == "recorder", User.speaker_id.isnot(None))
        .order_by(User.display_name, User.username)
        .all()
    )
    rows: list[dict] = []
    for user in recorders:
        recs = load_recordings(db, user.speaker_id, filters)  # type: ignore[arg-type]
        quality = _quality_block(recs)
        activity = _activity_block(recs)
        productivity = _productivity_block(recs)
        progress = progress_for_user(db, user)
        rows.append(
            {
                "user_id": user.id,
                "display_name": user.display_name or user.username,
                "username": user.username,
                "dataset_id": user.dataset_id,
                "dataset_name": user.dataset.name if user.dataset else None,
                "assigned": progress.get("assigned", 0),
                "completed": progress.get("completed", 0),
                "remaining": progress.get("remaining", 0),
                "skipped": progress.get("skipped", 0),
                "accepted": quality["accepted"],
                "acceptance_rate": quality["acceptance_rate"],
                "avg_qc_score": productivity["avg_qc_score"],
                "avg_time_per_script_sec": productivity["avg_time_per_script_sec"],
                "hours_recorded": productivity["hours_recorded"],
                "current_streak": activity["recording_streak"],
                "total_recordings": quality["total"],
            }
        )
    rows.sort(key=lambda r: (r["completed"], r["accepted"], r["acceptance_rate"]), reverse=True)
    return rows[:limit]


def list_recorder_summaries(db: Session, filters: AnalyticsFilter | None = None) -> list[dict]:
    return leaderboard(db, filters, limit=500)
