"""File-path management for recording masters.

Layout: data/audio/{speaker_key}/{script_id}/take_{n:02d}.wav
A storage abstraction point: swap this module for an object-storage client
(S3/OCI/Azure Blob) without touching the rest of the app.
"""
from __future__ import annotations

from pathlib import Path

from ..config import Settings


def take_rel_path(speaker_key: str, script_id: str, take_number: int) -> str:
    return f"{speaker_key}/{script_id}/take_{take_number:02d}.wav"


def abs_audio_path(settings: Settings, rel_path: str) -> Path:
    return settings.audio_dir / rel_path


def save_master(settings: Settings, rel_path: str, content: bytes) -> Path:
    path = abs_audio_path(settings, rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path
