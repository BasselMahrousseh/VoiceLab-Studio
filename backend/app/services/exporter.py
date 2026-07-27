"""Model-ready dataset export.

Output layout (per the agreed structure):

  exports/{batch_slug}/dataset/
    {speaker_key}/wavs/{script_id}.wav     (target rate, mono, PCM 16-bit)
    metadata.csv
    metadata.jsonl
    qc_report.json
    dataset_card.md

Masters are kept untouched; resampling/trimming/normalization happen only on
the exported copies.
"""
from __future__ import annotations

import csv
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Dataset, ExportBatch, Recording, Script
from .audio_io import (
    load_wav,
    loudness_normalize,
    peak_normalize,
    resample,
    write_wav_pcm16,
)
from .audio_qc import find_speech_bounds
from . import storage
from . import text_policy


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip()).strip("-").lower()
    return s or "export"


def run_export(db: Session, params: dict, settings: Settings) -> ExportBatch:
    name = params.get("name") or f"export_{datetime.now(timezone.utc):%Y%m%d_%H%M}"
    target_rate = int(params.get("sample_rate") or settings.export_sample_rate)
    trim_silence = bool(params.get("trim_silence", True))
    normalize_mode = params.get("normalize", "none")  # none | peak | loudness
    target_lufs = float(params.get("target_lufs", -20.0))
    dedupe_takes = bool(params.get("dedupe_takes", True))
    include_qc_warning = bool(params.get("include_qc_warning", True))
    styles = params.get("styles") or []
    domains = params.get("domains") or []
    make_zip = bool(params.get("make_zip", True))
    dataset_id = params.get("dataset_id")
    dataset = db.get(Dataset, dataset_id) if dataset_id else None

    q = (
        db.query(Recording)
        .filter(Recording.human_status == "accepted")
        .order_by(Recording.id)
    )
    if dataset_id:
        q = q.join(Script, Recording.script_pk == Script.id).filter(
            Script.dataset_id == dataset_id
        )
    recordings = [r for r in q.all()]
    # Filter in Python (JSON columns + joined fields keep this simple; volumes
    # here are thousands of rows, not millions).
    out: list[Recording] = []
    for r in recordings:
        if r.qc_status == "failed":
            continue
        if r.qc_status == "warning" and not include_qc_warning:
            continue
        if styles and r.script.style not in styles:
            continue
        if domains and r.script.domain not in domains:
            continue
        out.append(r)

    if dedupe_takes:
        latest: dict[tuple[int, int], Recording] = {}
        for r in out:
            # Keep one accepted take per utterance *per voice*. Collapsing only
            # by script would silently discard other assigned recorders.
            latest[(r.script_pk, r.speaker_id)] = r
        out = sorted(
            latest.values(),
            key=lambda r: (r.speaker.speaker_key, r.script.script_id),
        )
    else:
        out = sorted(out, key=lambda r: (r.script.script_id, r.take_number))

    batch_slug = f"{_slug(name)}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
    root = settings.export_dir / batch_slug / "dataset"
    root.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    total_dur = 0.0
    errors: list[str] = []
    multi_take_counts = Counter(r.script.script_id for r in out)

    for rec in out:
        try:
            audio = load_wav(storage.read_master(settings, rec.rel_path))
            x = audio.mono()
            if trim_silence:
                start, end = find_speech_bounds(x, audio.sample_rate)
                pad = int(settings.export_trim_pad_sec * audio.sample_rate)
                x = x[max(0, start - pad) : min(len(x), end + pad)]
            y = resample(x, audio.sample_rate, target_rate)
            if normalize_mode == "peak":
                y = peak_normalize(y, -3.0)
            elif normalize_mode == "loudness":
                y = loudness_normalize(y, target_rate, target_lufs)

            script = rec.script
            stem = script.script_id
            if not dedupe_takes and multi_take_counts[script.script_id] > 1:
                stem = f"{script.script_id}_t{rec.take_number:02d}"
            rel_audio = f"{rec.speaker.speaker_key}/wavs/{stem}.wav"
            write_wav_pcm16(root / rel_audio, y, target_rate)

            dur = round(len(y) / target_rate, 3)
            total_dur += dur
            rows.append(
                {
                    "audio_path": rel_audio,
                    "script_id": script.script_id,
                    "text": rec.final_text or script.training_text,
                    "display_text": script.display_text,
                    "msa_equivalent": script.msa_equivalent or "",
                    "speaker_id": rec.speaker.speaker_key,
                    "language": script.language,
                    "dialect": script.dialect,
                    "style": script.style,
                    "domain": script.domain,
                    "tags": ";".join(script.tags or []),
                    "duration_sec": dur,
                    "sample_rate": target_rate,
                    "session_id": rec.session_id,
                    "take_number": rec.take_number,
                    "text_edited": rec.text_edited,
                    "qc_status": rec.qc_status,
                    "asr_status": rec.asr_status,
                    "asr_cer": rec.asr_cer,
                    "snr_db": (rec.qc_metrics or {}).get("snr_db"),
                    "recorded_at": rec.created_at.isoformat() if rec.created_at else "",
                }
            )
        except Exception as exc:
            errors.append(f"{rec.script.script_id} take {rec.take_number}: {exc}")

    # --- metadata files -----------------------------------------------------
    if rows:
        with open(root / "metadata.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        with open(root / "metadata.jsonl", "w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    stats = {
        "clips": len(rows),
        "total_duration_sec": round(total_dur, 1),
        "total_duration_hms": _hms(total_dur),
        "by_style": dict(Counter(r["style"] for r in rows)),
        "by_domain": dict(Counter(r["domain"] for r in rows)),
        "by_language": dict(Counter(r["language"] for r in rows)),
        "by_speaker": dict(Counter(r["speaker_id"] for r in rows)),
        "by_dialect": dict(Counter(r["dialect"] for r in rows)),
        "by_qc_status": dict(Counter(r["qc_status"] for r in rows)),
        "avg_duration_sec": round(total_dur / len(rows), 2) if rows else 0,
        "errors": errors,
        "dataset_id": dataset.id if dataset else None,
        "dataset_name": dataset.name if dataset else "All datasets",
    }
    qc_report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": settings.dataset_version,
        "app_version": settings.app_version,
        "params": params,
        "stats": stats,
    }
    (root / "qc_report.json").write_text(
        json.dumps(qc_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (root / "dataset_card.md").write_text(_dataset_card(qc_report), encoding="utf-8")
    effective_policy = text_policy.get_policy(db)
    if dataset and dataset.text_policy.strip():
        effective_policy += "\n\n## Dataset-specific additions\n\n" + dataset.text_policy.strip()
    (root / "text_policy.md").write_text(effective_policy, encoding="utf-8")

    zip_rel = ""
    if make_zip and rows:
        zip_path = settings.export_dir / batch_slug / f"{batch_slug}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    zf.write(p, p.relative_to(root.parent))
        zip_rel = f"{batch_slug}/{batch_slug}.zip"

    # The generated tree includes dataset/ and, when requested, the ZIP beside it.
    storage.save_export_tree(settings, root.parent, batch_slug)

    batch = ExportBatch(
        name=name,
        params=params,
        stats=stats,
        rel_path=f"{batch_slug}/dataset",
        zip_rel_path=zip_rel,
        file_count=len(rows),
        total_duration_sec=round(total_dur, 1),
        dataset_version=settings.dataset_version,
        status="done" if rows else "failed",
        error="" if rows else "No accepted recordings matched the export filters",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


def _hms(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _dataset_card(report: dict) -> str:
    stats = report["stats"]
    return f"""# {stats['dataset_name']}

- Generated: {report['generated_at']}
- Dataset version: {report['dataset_version']} (VoiceLab Studio {report['app_version']})
- Clips: {stats['clips']}
- Total duration: {stats['total_duration_hms']} ({stats['total_duration_sec']} s)
- Average clip: {stats['avg_duration_sec']} s

## Composition

- By language: {json.dumps(stats['by_language'], ensure_ascii=False)}
- By speaker: {json.dumps(stats['by_speaker'], ensure_ascii=False)}
- By style: {json.dumps(stats['by_style'], ensure_ascii=False)}
- By domain: {json.dumps(stats['by_domain'], ensure_ascii=False)}
- By dialect: {json.dumps(stats['by_dialect'], ensure_ascii=False)}

## Files

- `metadata.csv` / `metadata.jsonl` — one row per clip. `text` is the training
  transcript (exact spoken words, Emirati preserved); `display_text` is what
  the speaker saw; `msa_equivalent` is supplementary metadata only.
- `qc_report.json` — export parameters and aggregate quality stats.
- `text_policy.md` — effective global policy plus this dataset's additions.
- Audio: mono PCM 16-bit WAV at {report['params'].get('sample_rate', 'target')} Hz.

Transcripts follow the included `text_policy.md`. Every row carries its
per-sentence `language`, `dialect`, style, domain and tags.
"""
