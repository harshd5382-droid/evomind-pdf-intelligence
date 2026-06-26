"""Shared pytest fixtures + zero-infra test environment.

This module is imported by pytest *before* any test module, so the os.environ
setup here runs before `app.*` is first imported — which matters because
`app.db.postgres` builds its engine from POSTGRES_DSN at import time. We point
everything at SQLite + in-memory stores so the suite needs no Docker.
"""
from __future__ import annotations

import os
import tempfile

# --- Zero-infra environment (must be set before importing app modules) ---
# ignore_cleanup_errors: on Windows a lingering file handle (e.g. a backup zip
# served via FileResponse) can make rmtree raise at session end; that must not
# fail the suite.
_tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
_root = _tmp.name
os.environ.setdefault("POSTGRES_DSN", f"sqlite:///{os.path.join(_root, 'test.db')}")
os.environ.setdefault("REDIS_URL", "memory://")
os.environ.setdefault("QDRANT_URL", "memory://")
os.environ.setdefault("NEO4J_URI", "")
os.environ.setdefault("DATA_DIR", _root)
os.environ.setdefault("UPLOAD_DIR", os.path.join(_root, "uploads"))
os.environ.setdefault("AUTOPILOT_ENABLED", "false")
os.environ.setdefault("AUTO_INGEST_ENABLED", "false")
os.environ.setdefault("PRIMARY_PROVIDER", "ollama")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")

import pytest  # noqa: E402
from app.db import postgres  # noqa: E402
from app.db.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init_db():
    """Create the schema once for the whole session."""
    postgres.init_db()
    yield
    postgres.engine.dispose()
    try:
        _tmp.cleanup()
    except Exception:
        pass


@pytest.fixture
def clean_db():
    """Truncate every table before a test that asserts on exact counts.

    Deletes in reverse metadata order so FK constraints (answers→questions,
    chunks→documents) are satisfied.
    """
    with postgres.session_scope() as s:
        for table in reversed(Base.metadata.sorted_tables):
            s.execute(table.delete())
    yield


@pytest.fixture
def client():
    """A FastAPI TestClient. Lifespan is intentionally NOT entered (no `with`),
    so the autopilot / folder-watcher threads never start during tests."""
    from app.main import create_app
    from fastapi.testclient import TestClient

    return TestClient(create_app())
