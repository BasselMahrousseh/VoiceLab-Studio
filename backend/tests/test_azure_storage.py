from pathlib import Path

from app.config import Settings
from app.services import storage
from app.services.database_backup import backup_sqlite


class FakeDownloader:
    def __init__(self, content: bytes):
        self.content = content

    def readall(self):
        return self.content

    def chunks(self):
        yield self.content


class FakeBlob:
    def __init__(self, blobs: dict[str, bytes], name: str):
        self.blobs = blobs
        self.name = name

    def upload_blob(self, content, overwrite=False, **_kwargs):
        assert overwrite is True
        self.blobs[self.name] = bytes(content)

    def download_blob(self):
        return FakeDownloader(self.blobs[self.name])

    def delete_blob(self, **_kwargs):
        self.blobs.pop(self.name)


class FakeContainer:
    def __init__(self):
        self.blobs: dict[str, bytes] = {}

    def get_blob_client(self, name: str):
        return FakeBlob(self.blobs, name)


def blob_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        storage_backend="azure_blob",
        azure_storage_account_url="https://example.blob.core.windows.net",
        azure_storage_container="voicelab",
        azure_client_id="test-client",
        _env_file=None,
    )


def test_blob_master_and_export_round_trip(tmp_path, monkeypatch):
    settings = blob_settings(tmp_path)
    fake = FakeContainer()
    monkeypatch.setattr(storage, "_container", lambda _settings: fake)

    rel = storage.take_rel_path("speaker_001", "AE_001", 1)
    storage.save_master(settings, rel, b"wav")
    assert fake.blobs[f"audio/{rel}"] == b"wav"
    assert storage.read_master(settings, rel) == b"wav"
    storage.delete_master(settings, rel)
    assert f"audio/{rel}" not in fake.blobs

    export_root = tmp_path / "batch"
    export_root.mkdir()
    (export_root / "dataset.zip").write_bytes(b"zip")
    storage.save_export_tree(settings, export_root, "batch")
    assert b"".join(storage.iter_export(settings, "batch/dataset.zip")) == b"zip"


def test_sqlite_backup_is_consistent_and_uploaded(tmp_path, monkeypatch):
    import sqlite3

    settings = blob_settings(tmp_path)
    fake = FakeContainer()
    monkeypatch.setattr(storage, "_container", lambda _settings: fake)

    with sqlite3.connect(tmp_path / "voicelab.db") as db:
        db.execute("create table sample (value text)")
        db.execute("insert into sample values ('kept')")

    result = backup_sqlite(settings)
    key = f"database-backups/{result['name']}"
    assert key in fake.blobs
    assert result["size_bytes"] == len(fake.blobs[key])
