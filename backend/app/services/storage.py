"""Recording and export storage.

Layout: data/audio/{speaker_key}/{script_id}/take_{n:02d}.wav
Azure layout inside the configured container:
  audio/{speaker_key}/{script_id}/take_{n:02d}.wav
  exports/{batch_slug}/...
  database-backups/voicelab_{timestamp}.db
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterator

from ..config import Settings


def _safe_rel_path(rel_path: str) -> str:
    normalized = rel_path.replace("\\", "/").strip("/")
    if not normalized or any(part in ("", ".", "..") for part in normalized.split("/")):
        raise ValueError("Invalid storage path")
    return normalized


def _blob_name(prefix: str, rel_path: str) -> str:
    return f"{prefix.strip('/')}/{_safe_rel_path(rel_path)}"


@lru_cache(maxsize=8)
def _container_client(account_url: str, container: str, client_id: str):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import ContainerClient

    credential = DefaultAzureCredential(
        managed_identity_client_id=client_id or None,
        exclude_interactive_browser_credential=True,
    )
    return ContainerClient(
        account_url=account_url,
        container_name=container,
        credential=credential,
    )


def _container(settings: Settings):
    if not settings.blob_storage_configured():
        raise RuntimeError(
            "Azure Blob storage is not fully configured. Set STORAGE_BACKEND, "
            "AZURE_STORAGE_ACCOUNT_URL and AZURE_STORAGE_CONTAINER."
        )
    return _container_client(
        settings.azure_storage_account_url,
        settings.azure_storage_container,
        settings.azure_client_id,
    )


def take_rel_path(speaker_key: str, script_id: str, take_number: int) -> str:
    return f"{speaker_key}/{script_id}/take_{take_number:02d}.wav"


def abs_audio_path(settings: Settings, rel_path: str) -> Path:
    """Return a local master path. Only valid for the local backend."""
    if settings.storage_backend != "local":
        raise RuntimeError("Azure Blob masters do not have a persistent local path")
    return settings.audio_dir / _safe_rel_path(rel_path)


def save_master(settings: Settings, rel_path: str, content: bytes) -> Path:
    if settings.storage_backend == "azure_blob":
        from azure.storage.blob import ContentSettings

        blob = _container(settings).get_blob_client(
            _blob_name(settings.azure_storage_audio_prefix, rel_path)
        )
        blob.upload_blob(
            content,
            overwrite=True,
            content_settings=ContentSettings(content_type="audio/wav"),
        )
        # Callers persist only rel_path; the returned path is for local compatibility.
        return Path(_safe_rel_path(rel_path))

    path = abs_audio_path(settings, rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def read_master(settings: Settings, rel_path: str) -> bytes:
    if settings.storage_backend == "azure_blob":
        blob = _container(settings).get_blob_client(
            _blob_name(settings.azure_storage_audio_prefix, rel_path)
        )
        return blob.download_blob().readall()
    return abs_audio_path(settings, rel_path).read_bytes()


def save_export_tree(settings: Settings, root: Path, batch_rel_path: str) -> None:
    """Persist all generated export files when Blob storage is enabled."""
    if settings.storage_backend != "azure_blob":
        return
    for path in root.rglob("*"):
        if path.is_file():
            from azure.storage.blob import ContentSettings

            relative = path.relative_to(root).as_posix()
            blob_name = _blob_name(
                settings.azure_storage_export_prefix,
                f"{batch_rel_path}/{relative}",
            )
            content_type = (
                "application/zip"
                if path.suffix == ".zip"
                else "audio/wav"
                if path.suffix == ".wav"
                else "application/json"
                if path.suffix in (".json", ".jsonl")
                else "text/csv"
                if path.suffix == ".csv"
                else "text/markdown"
                if path.suffix == ".md"
                else "application/octet-stream"
            )
            _container(settings).get_blob_client(blob_name).upload_blob(
                path.read_bytes(),
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
            )


def iter_export(
    settings: Settings, rel_path: str, chunk_size: int = 4 * 1024 * 1024
) -> Iterator[bytes]:
    if settings.storage_backend == "azure_blob":
        downloader = _container(settings).get_blob_client(
            _blob_name(settings.azure_storage_export_prefix, rel_path)
        ).download_blob()
        yield from downloader.chunks()
        return

    path = settings.export_dir / _safe_rel_path(rel_path)
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


def save_database_backup(settings: Settings, path: Path) -> str:
    rel_path = path.name
    if settings.storage_backend == "azure_blob":
        from azure.storage.blob import ContentSettings

        blob_name = _blob_name(settings.azure_storage_backup_prefix, rel_path)
        _container(settings).get_blob_client(blob_name).upload_blob(
            path.read_bytes(),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/x-sqlite3"),
        )
    else:
        destination = settings.data_dir / "database-backups" / rel_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    return rel_path
