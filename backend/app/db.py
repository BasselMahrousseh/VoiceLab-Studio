from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker | None = None


def init_db() -> None:
    """Create the engine, tables and seed data. Called on app startup."""
    global _engine, _SessionLocal
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.audio_dir.mkdir(parents=True, exist_ok=True)
    settings.export_dir.mkdir(parents=True, exist_ok=True)

    url = settings.resolved_database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    _engine = create_engine(url, connect_args=connect_args)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(_engine)
    _migrate_sqlite()
    _seed_defaults()


def _migrate_sqlite() -> None:
    """Add columns introduced after the DB was first created.

    ``create_all`` never ALTERs existing tables, so a database created before
    the auth/dataset features would miss ``scripts.dataset_id``. This tops up
    only-missing columns; it is a no-op on a fresh DB and skipped for non-sqlite
    backends (use a real migration tool there).
    """
    assert _engine is not None
    if _engine.dialect.name != "sqlite":
        return
    from sqlalchemy import text

    wanted = {
        "scripts": [("dataset_id", "INTEGER")],
        "datasets": [
            ("target_sample_count", "INTEGER DEFAULT 0"),
            ("target_avg_duration_sec", "REAL DEFAULT 0"),
            ("languages", "TEXT DEFAULT '[\"ar-AE\"]'"),
            ("text_policy", "TEXT DEFAULT ''"),
        ],
    }
    with _engine.begin() as conn:
        for table, columns in wanted.items():
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            for name, decl in columns:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {decl}"))


def _seed_defaults() -> None:
    from .models import Dataset, Speaker, User
    from .services import auth as auth_svc

    settings = get_settings()
    with session_scope() as db:
        if not db.query(Speaker).filter_by(speaker_key=settings.default_speaker_key).first():
            db.add(
                Speaker(
                    speaker_key=settings.default_speaker_key,
                    display_name=settings.default_speaker_name,
                )
            )
        # A default dataset so pre-existing scripts (dataset_id NULL) and the
        # admin's own recording have a home to attach to.
        if not db.query(Dataset).filter_by(slug="default").first():
            db.add(
                Dataset(
                    slug="default",
                    name="Default dataset",
                    description="Scripts not assigned to a specific dataset.",
                    instructions=_DEFAULT_INSTRUCTIONS,
                )
            )
        # Seed an admin so the login screen is usable on first run.
        if not db.query(User).filter_by(role="admin").first():
            db.add(
                User(
                    username=settings.default_admin_username,
                    password_hash=auth_svc.hash_password(settings.default_admin_password),
                    role="admin",
                    display_name=settings.default_admin_name,
                )
            )
        db.commit()


_DEFAULT_INSTRUCTIONS = (
    "• Record in a quiet room with no echo, fans, or background voices.\n"
    "• Keep a steady hand-width distance from the microphone.\n"
    "• Read the sentence exactly as shown, in its natural language and dialect.\n"
    "• Speak at a calm, even pace — don't rush the ends of sentences.\n"
    "• If you stumble or mispronounce, just press Restart and read it again.\n"
    "• Leave a short beat of silence before you start and after you finish."
)


def get_db():
    """FastAPI dependency yielding a DB session."""
    assert _SessionLocal is not None, "init_db() has not been called"
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


class session_scope:
    """Context manager for non-request code paths (startup, scripts)."""

    def __enter__(self) -> Session:
        assert _SessionLocal is not None, "init_db() has not been called"
        self.db = _SessionLocal()
        return self.db

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.db.rollback()
        self.db.close()
