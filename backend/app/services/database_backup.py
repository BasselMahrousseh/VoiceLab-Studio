"""Consistent SQLite backups for the single-instance App Service deployment."""
from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings
from . import storage


def backup_sqlite(settings: Settings) -> dict[str, str | int]:
    if settings.database_url and not settings.database_url.startswith("sqlite"):
        raise RuntimeError("Database backups through this endpoint support SQLite only")

    source = settings.data_dir / "voicelab.db"
    if not source.exists():
        raise FileNotFoundError(f"SQLite database not found: {source}")

    name = f"voicelab_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.db"
    with tempfile.TemporaryDirectory(prefix="voicelab-backup-") as temp_dir:
        backup_path = Path(temp_dir) / name
        with closing(sqlite3.connect(source)) as src:
            with closing(sqlite3.connect(backup_path)) as dst:
                src.backup(dst)
        storage.save_database_backup(settings, backup_path)
        size = backup_path.stat().st_size

    return {"name": name, "size_bytes": size}
