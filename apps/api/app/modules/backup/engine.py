"""On-demand backups of the durable state.

PostgreSQL/SQLite is the source of truth (documents, chunks, questions, answers,
insights, hypotheses, memories, conversations, ...). Qdrant vectors and the Neo4j
graph are *derivable* by re-ingesting/re-synthesising, so they are backed up
best-effort and their absence is not fatal.

Each backup is a timestamped folder under `<data_dir>/backups/<id>/` containing
the DB dump plus a `manifest.json` describing what was captured.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import get_settings
from app.db import postgres


def backup_dir_path() -> Path:
    root = Path(get_settings().data_dir) / "backups"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _new_id() -> str:
    # Microsecond precision so rapid successive backups (and the test suite)
    # never collide on the same folder id.
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")


def _backup_database(dest: Path) -> dict:
    """Dump the DB. SQLite → online .backup(); Postgres → pg_dump."""
    url = postgres.engine.url
    backend = postgres.backend_name()
    try:
        if backend == "sqlite":
            src_file = url.database
            if not src_file or src_file == ":memory:":
                return {"ok": False, "backend": backend, "skipped": "in-memory database"}
            out = dest / "database.sqlite"
            src = sqlite3.connect(src_file)
            try:
                dst = sqlite3.connect(str(out))
                try:
                    src.backup(dst)  # consistent online snapshot
                finally:
                    dst.close()
            finally:
                src.close()
            return {"ok": True, "backend": backend, "file": out.name, "bytes": out.stat().st_size}

        if backend == "postgresql":
            # Build a libpq URL (strip the SQLAlchemy "+driver" suffix).
            libpq = url.set(drivername="postgresql").render_as_string(hide_password=False)
            out = dest / "database.sql"
            proc = subprocess.run(
                ["pg_dump", "--no-owner", "--no-privileges", "-f", str(out), libpq],
                capture_output=True, text=True, timeout=600,
            )
            if proc.returncode != 0:
                return {"ok": False, "backend": backend, "error": proc.stderr.strip()[:500]}
            return {"ok": True, "backend": backend, "file": out.name, "bytes": out.stat().st_size}

        return {"ok": False, "backend": backend, "skipped": f"unsupported backend {backend}"}
    except FileNotFoundError:
        # pg_dump not installed
        return {"ok": False, "backend": backend, "error": "pg_dump not found on PATH"}
    except Exception as e:  # noqa: BLE001 - backup must report, not crash
        logger.warning("DB backup failed: {}", e)
        return {"ok": False, "backend": backend, "error": str(e)[:500]}


def _backup_qdrant() -> dict:
    """Best-effort server-side Qdrant snapshot. Vectors are re-derivable from
    chunks, so memory-mode / unreachable just records a skip."""
    from app.db import qdrant
    try:
        c = qdrant.client()
        if c is None:
            return {"ok": False, "skipped": "in-memory vector store (re-derivable)"}
        snap = c.create_snapshot(collection_name=get_settings().qdrant_collection)
        name = getattr(snap, "name", str(snap))
        return {"ok": True, "snapshot": name, "note": "stored server-side on Qdrant"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}


def _backup_neo4j() -> dict:
    """Neo4j graph is derivable from Postgres; we only note reachability."""
    from app.db import neo4j_store
    try:
        st = neo4j_store.status()
        if not st.get("reachable"):
            return {"ok": False, "skipped": "neo4j not configured/reachable (re-derivable)"}
        return {"ok": False, "skipped": "online dump not implemented; graph is re-derivable from Postgres"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}


def create_backup() -> dict:
    """Create a new backup folder and return its manifest."""
    bid = _new_id()
    dest = backup_dir_path() / bid
    dest.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "id": bid,
        "created_at": datetime.utcnow().isoformat(),
        "components": {
            "database": _backup_database(dest),
            "qdrant": _backup_qdrant(),
            "neo4j": _backup_neo4j(),
        },
    }
    manifest["ok"] = bool(manifest["components"]["database"].get("ok"))
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Backup {} created (db_ok={})", bid, manifest["ok"])
    return manifest


def _read_manifest(folder: Path) -> dict | None:
    mf = folder / "manifest.json"
    if not mf.exists():
        return None
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_backups() -> list[dict]:
    """Newest first."""
    out = []
    for folder in sorted(backup_dir_path().iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        mf = _read_manifest(folder)
        if mf:
            total = sum(
                f.stat().st_size for f in folder.glob("*") if f.is_file()
            )
            out.append({**mf, "size_bytes": total})
    return out


def backup_status() -> dict:
    backups = list_backups()
    return {
        "count": len(backups),
        "latest": backups[0] if backups else None,
        "backup_dir": str(backup_dir_path()),
    }
