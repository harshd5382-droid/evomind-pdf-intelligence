"""Folder watcher — auto-ingest any PDF dropped into a watched directory.

The user's only job is to drop PDFs (or a folder of PDFs) into the watched
directory. The watcher:

  • scans recursively every `auto_ingest_interval_sec` seconds
  • waits for each file to be stable (mtime unchanged for `auto_ingest_stable_sec` seconds)
    so partially-copied files aren't ingested mid-write
  • skips PDFs already represented in `documents.path` so re-runs are idempotent
  • enqueues the file into the in-process ingest queue (or Celery if available)

Configured via `auto_ingest_*` settings in `app.core.config`.
"""
from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from loguru import logger
from sqlalchemy import select

from app.core.config import get_settings
from app.db import postgres
from app.db.models import Document, Job

_thread: threading.Thread | None = None
_stop = threading.Event()
_started_lock = threading.Lock()
_seen: set[str] = set()       # absolute paths already enqueued this process
_mtimes: dict[str, float] = {} # path → last-seen mtime, used for stability check


def _enqueue(file_path: str, doc_id: str, job_id: str) -> None:
    """Try Celery first; fall back to the in-process queue. Mirrors routes._enqueue_ingest."""
    try:
        from app.workers.tasks import ingest_task
        ingest_task.delay(file_path, document_id=doc_id, job_id=job_id)
        return
    except Exception:
        pass
    from app.workers.inproc_queue import submit_ingest
    submit_ingest(file_path, doc_id, job_id)


def _already_ingested(abs_path: str) -> bool:
    """True if a Document with this absolute path already exists."""
    try:
        with postgres.session_scope() as s:
            row = s.execute(select(Document.id).where(Document.path == abs_path)).first()
            return row is not None
    except Exception:
        return False


def _hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 of the file's bytes, streamed."""
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def _content_already_ingested(content_hash: str) -> tuple[bool, str | None]:
    """True if a Document with this SHA-256 already exists. Returns (exists, original_filename)."""
    if not content_hash:
        return (False, None)
    try:
        with postgres.session_scope() as s:
            row = s.execute(
                select(Document.id, Document.filename).where(Document.content_hash == content_hash)
            ).first()
            return (row is not None, row[1] if row else None)
    except Exception:
        return (False, None)


def _is_stable(p: Path, min_stable_sec: float) -> bool:
    """Return True only if the file's mtime hasn't changed for `min_stable_sec`."""
    try:
        mt = p.stat().st_mtime
    except OSError:
        return False
    key = str(p)
    last = _mtimes.get(key)
    _mtimes[key] = mt
    if last is None:
        return False
    if mt != last:
        return False
    return (time.time() - mt) >= min_stable_sec


def _drain_mode_active() -> tuple[bool, int]:
    """If queue depth exceeds the configured threshold, pause new pickups.
    Returns (active, current_depth)."""
    s = get_settings()
    threshold = int(getattr(s, "auto_ingest_drain_threshold", 0) or 0)
    if threshold <= 0:
        return (False, 0)
    try:
        from app.workers.inproc_queue import queue_stats
        depth = int(queue_stats().get("queued", 0))
        return (depth >= threshold, depth)
    except Exception:
        return (False, 0)


def _scan_once(folder: Path, stable_sec: float) -> int:
    """Return number of files newly enqueued this pass."""
    enqueued = 0
    drain, depth = _drain_mode_active()
    if drain:
        # Don't pick anything up — let the autopilot catch up on solving.
        # Logged at debug to avoid spamming the log; surfaced via /folder-watcher/status.
        logger.debug("folder_watcher: drain mode (queue={} ≥ threshold), skipping scan", depth)
        return 0
    try:
        pdfs = sorted(folder.rglob("*.pdf"))
    except Exception as e:
        logger.warning("folder_watcher: scan failed for {}: {}", folder, e)
        return 0

    for pdf in pdfs:
        try:
            abs_path = str(pdf.resolve())
        except Exception:
            continue
        if abs_path in _seen:
            continue
        if not _is_stable(pdf, stable_sec):
            continue
        if _already_ingested(abs_path):
            _seen.add(abs_path)
            continue

        # Content-hash dedup: catches the same PDF copied under a different
        # filename/path (e.g. user drops it again as "paper-final-v2.pdf").
        try:
            content_hash = _hash_file(pdf)
        except Exception as e:
            logger.warning("folder_watcher: hash failed for {}: {}", pdf, e)
            content_hash = ""
        dup, original = _content_already_ingested(content_hash)
        if dup:
            _seen.add(abs_path)
            logger.info("folder_watcher: skipped duplicate of '{}': {}", original, pdf.name)
            continue

        doc_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        try:
            with postgres.session_scope() as s:
                s.add(Job(
                    id=job_id, kind="ingest", target_id=doc_id,
                    status="queued", detail=pdf.name,
                ))
                # Pre-register the document with its hash so a second drop of the
                # same file mid-processing can't slip through the dedup gate.
                s.add(Document(
                    id=doc_id, title=pdf.stem, filename=pdf.name,
                    path=abs_path, content_hash=content_hash, status="pending",
                ))
        except Exception as e:
            logger.warning("folder_watcher: could not record job for {}: {}", pdf, e)
            continue

        try:
            _enqueue(abs_path, doc_id, job_id)
            _seen.add(abs_path)
            enqueued += 1
            logger.info("folder_watcher: enqueued {}", pdf.name)
        except Exception as e:
            logger.warning("folder_watcher: enqueue failed for {}: {}", pdf, e)
    return enqueued


def _loop() -> None:
    s = get_settings()
    folder = Path(s.auto_ingest_dir).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    logger.info(
        "folder_watcher: watching {} (interval={}s, stable={}s)",
        folder, s.auto_ingest_interval_sec, s.auto_ingest_stable_sec,
    )

    while not _stop.is_set():
        try:
            _scan_once(folder, s.auto_ingest_stable_sec)
        except Exception as e:
            logger.exception("folder_watcher: scan crashed (continuing): {}", e)
        _stop.wait(timeout=max(2, s.auto_ingest_interval_sec))

    logger.info("folder_watcher: stopped")


def start() -> None:
    """Start the watcher daemon thread (idempotent)."""
    global _thread
    s = get_settings()
    if not s.auto_ingest_enabled:
        logger.info("folder_watcher: disabled by config")
        return

    with _started_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="evomind-folder-watcher", daemon=True)
        _thread.start()


def stop(timeout: float = 4.0) -> None:
    _stop.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=timeout)


def status() -> dict:
    s = get_settings()
    folder = Path(s.auto_ingest_dir).expanduser()
    try:
        watching = str(folder.resolve())
    except Exception:
        watching = str(folder)
    drain, depth = _drain_mode_active()
    return {
        "enabled": bool(s.auto_ingest_enabled),
        "running": bool(_thread and _thread.is_alive()),
        "watching": watching,
        "exists": folder.exists(),
        "interval_sec": s.auto_ingest_interval_sec,
        "stable_sec": s.auto_ingest_stable_sec,
        "seen_in_process": len(_seen),
        "drain_mode": drain,
        "drain_threshold": int(getattr(s, "auto_ingest_drain_threshold", 0) or 0),
        "current_queue_depth": depth,
    }
