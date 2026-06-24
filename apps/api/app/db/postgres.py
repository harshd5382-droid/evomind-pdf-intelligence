from contextlib import contextmanager
from typing import Iterator

from loguru import logger
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base

_settings = get_settings()
engine = create_engine(_settings.postgres_dsn, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    """Create tables and apply lightweight in-place migrations.

    SQLAlchemy's create_all only creates *missing* tables; it does NOT add new
    columns to existing ones. We do a small targeted ALTER for columns added
    after the initial schema (e.g. Document.content_hash). This keeps zero-infra
    SQLite databases working across upgrades without needing Alembic.
    """
    Base.metadata.create_all(engine)
    _apply_simple_migrations()


def _apply_simple_migrations() -> None:
    """Idempotent ALTERs for columns added after initial release."""
    try:
        insp = inspect(engine)
        names = set(insp.get_table_names())

        # documents.content_hash — Day 10 dedup
        if "documents" in names:
            cols = {c["name"] for c in insp.get_columns("documents")}
            if "content_hash" not in cols:
                logger.info("Migrating: adding documents.content_hash column")
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE documents ADD COLUMN content_hash VARCHAR(64)"))
                    try:
                        conn.execute(text(
                            "CREATE INDEX IF NOT EXISTS ix_documents_content_hash "
                            "ON documents (content_hash)"
                        ))
                    except Exception as e:
                        logger.debug("content_hash index create skipped: {}", e)

        # memories.{embedding, source_kind, source_id} — Day 11 living memory
        if "memories" in names:
            cols = {c["name"] for c in insp.get_columns("memories")}
            with engine.begin() as conn:
                if "embedding" not in cols:
                    logger.info("Migrating: adding memories.embedding column")
                    conn.execute(text("ALTER TABLE memories ADD COLUMN embedding JSON"))
                if "source_kind" not in cols:
                    logger.info("Migrating: adding memories.source_kind column")
                    conn.execute(text("ALTER TABLE memories ADD COLUMN source_kind VARCHAR(32)"))
                if "source_id" not in cols:
                    logger.info("Migrating: adding memories.source_id column")
                    conn.execute(text("ALTER TABLE memories ADD COLUMN source_id VARCHAR(36)"))
    except Exception as e:
        logger.warning("Simple migration pass failed (continuing): {}", e)


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def backend_name() -> str:
    driver = engine.url.drivername or ""
    if driver.startswith("sqlite"):
        return "sqlite"
    if driver.startswith("postgresql"):
        return "postgresql"
    return driver or "unknown"


def status() -> dict:
    backend = backend_name()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        reachable = True
        error = None
    except Exception as exc:
        reachable = False
        error = str(exc)
    database = engine.url.database or ""
    return {
        "backend": backend,
        "reachable": reachable,
        "database": database,
        "in_memory": backend == "sqlite" and database == ":memory:",
        "error": error,
    }
