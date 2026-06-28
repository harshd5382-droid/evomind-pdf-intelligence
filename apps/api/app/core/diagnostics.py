from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import neo4j_store, postgres, qdrant, redis_client
from app.db.models import (
    Answer,
    Chunk,
    Contradiction,
    Document,
    Hypothesis,
    Insight,
    Job,
    Memory,
    Question,
)


def _now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def _parse_event_time(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value if value > 10_000_000_000 else value * 1000)
    if isinstance(value, str):
        try:
            return int(float(value))
        except Exception:
            pass
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            return None
    return None


def _provider_configured(provider: str) -> bool:
    s = get_settings()
    provider = (provider or "").lower()
    if provider == "nvidia":
        return bool(s.nvidia_api_key)
    if provider == "anthropic":
        return bool(s.anthropic_api_key)
    if provider == "openai":
        return bool(s.openai_api_key)
    if provider == "gemini":
        return bool(s.gemini_api_key)
    if provider == "ollama":
        return bool(s.ollama_base_url)
    if provider == "local":
        return True
    return False


def _runtime_mode() -> str:
    s = get_settings()
    db_kind = postgres.backend_name()
    redis_mode = redis_client.mode()
    qdrant_mode = qdrant.mode()
    if db_kind == "sqlite" and redis_mode == "memory" and qdrant_mode == "memory" and not s.neo4j_uri:
        return "local-zero-infra"
    if db_kind == "postgresql" and redis_mode == "redis" and qdrant_mode == "qdrant" and s.neo4j_uri:
        return "full-stack"
    return "hybrid"


def integrity_report(*, repair: bool = False) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "checked_at": datetime.utcnow().isoformat(),
        "repair_performed": repair,
        "repairs": {
            "jobs_marked_succeeded": 0,
            "documents_marked_ready": 0,
        },
        "counts": {},
        "failed_jobs": [],
    }

    with postgres.session_scope() as s:
        orphan_questions = s.execute(
            select(func.count(Question.id))
            .outerjoin(Document, Question.document_id == Document.id)
            .where(Question.document_id.is_not(None), Document.id.is_(None))
        ).scalar() or 0
        orphan_answers = s.execute(
            select(func.count(Answer.id))
            .outerjoin(Question, Answer.question_id == Question.id)
            .where(Question.id.is_(None))
        ).scalar() or 0
        orphan_chunks = s.execute(
            select(func.count(Chunk.id))
            .outerjoin(Document, Chunk.document_id == Document.id)
            .where(Document.id.is_(None))
        ).scalar() or 0
        duplicate_paths = s.execute(
            select(func.count()).select_from(
                select(Document.path)
                .group_by(Document.path)
                .having(func.count(Document.id) > 1)
                .subquery()
            )
        ).scalar() or 0
        duplicate_hashes = s.execute(
            select(func.count()).select_from(
                select(Document.content_hash)
                .where(Document.content_hash.is_not(None))
                .group_by(Document.content_hash)
                .having(func.count(Document.id) > 1)
                .subquery()
            )
        ).scalar() or 0
        pending_with_chunks = s.execute(
            select(func.count(Document.id))
            .join(Chunk, Chunk.document_id == Document.id)
            .where(Document.status == "pending")
            .group_by(Document.id)
        ).all()
        failed_jobs = (
            s.query(Job, Document)
            .outerjoin(Document, Job.target_id == Document.id)
            .filter(Job.status == "failed")
            .order_by(Job.created_at.desc())
            .all()
        )
        stale_running = (
            s.query(Job, Document)
            .outerjoin(Document, Job.target_id == Document.id)
            .filter(Job.kind == "ingest", Job.status.in_(("queued", "running")))
            .all()
        )
        missing_memory_links = {
            "insight": s.execute(
                select(func.count(Memory.id))
                .outerjoin(Insight, Memory.source_id == Insight.id)
                .where(Memory.source_kind == "insight", Insight.id.is_(None))
            ).scalar() or 0,
            "hypothesis": s.execute(
                select(func.count(Memory.id))
                .outerjoin(Hypothesis, Memory.source_id == Hypothesis.id)
                .where(Memory.source_kind == "hypothesis", Hypothesis.id.is_(None))
            ).scalar() or 0,
            "contradiction": s.execute(
                select(func.count(Memory.id))
                .outerjoin(Contradiction, Memory.source_id == Contradiction.id)
                .where(Memory.source_kind == "contradiction", Contradiction.id.is_(None))
            ).scalar() or 0,
        }

        if repair:
            pending_docs = (
                s.query(Document)
                .join(Chunk, Chunk.document_id == Document.id)
                .filter(Document.status == "pending")
                .all()
            )
            seen_docs: set[str] = set()
            for doc in pending_docs:
                if doc.id in seen_docs:
                    continue
                seen_docs.add(doc.id)
                doc.status = "ready"
                summary["repairs"]["documents_marked_ready"] += 1

            for job, doc in failed_jobs + stale_running:
                if not doc or job.kind != "ingest":
                    continue
                chunk_count = s.execute(
                    select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)
                ).scalar() or 0
                if doc.status == "ready" and chunk_count > 0:
                    job.status = "succeeded"
                    if not job.finished_at:
                        job.finished_at = datetime.utcnow()
                    detail = (job.detail or "").strip()
                    if "[auto-repaired]" not in detail:
                        suffix = "[auto-repaired] document ingest completed despite earlier job failure."
                        job.detail = f"{detail} {suffix}".strip()
                    summary["repairs"]["jobs_marked_succeeded"] += 1

        repairable_failed_jobs = []
        for job, doc in failed_jobs:
            chunk_count = 0
            if doc:
                chunk_count = s.execute(
                    select(func.count(Chunk.id)).where(Chunk.document_id == doc.id)
                ).scalar() or 0
            repairable = bool(doc and doc.status == "ready" and chunk_count > 0 and job.kind == "ingest")
            summary["failed_jobs"].append({
                "job_id": job.id,
                "kind": job.kind,
                "status": job.status,
                "detail": (job.detail or "")[:240],
                "document_id": doc.id if doc else None,
                "document_title": doc.title if doc else None,
                "document_status": doc.status if doc else None,
                "repairable": repairable,
            })
            if repairable:
                repairable_failed_jobs.append(job.id)

        summary["counts"] = {
            "orphan_questions": orphan_questions,
            "orphan_answers": orphan_answers,
            "orphan_chunks": orphan_chunks,
            "duplicate_paths": duplicate_paths,
            "duplicate_hashes": duplicate_hashes,
            "pending_documents_with_chunks": len(pending_with_chunks),
            "failed_jobs": len(failed_jobs),
            "repairable_failed_jobs": len(repairable_failed_jobs),
            "stale_ingest_jobs": len(stale_running),
            "missing_memory_links": missing_memory_links,
        }

    return summary


def collect_runtime_diagnostics() -> dict[str, Any]:
    from app.modules import autopilot, folder_watcher

    s = get_settings()
    db_status = postgres.status()
    redis_status = redis_client.status()
    qdrant_status = qdrant.status()
    graph_status = neo4j_store.status()
    integrity = integrity_report(repair=False)
    recent = redis_client.recent_events(1)
    last_event = recent[0] if recent else None
    last_event_time = None
    if last_event:
        for key in ("_t", "timestamp", "ts", "created_at"):
            last_event_time = _parse_event_time(last_event.get(key))
            if last_event_time is not None:
                break
        if last_event_time is None:
            last_event_time = _now_ms()

    issues: list[dict[str, str]] = []
    if not db_status["reachable"]:
        issues.append({"level": "error", "message": "Database is not reachable."})
    if not _provider_configured(s.primary_provider):
        issues.append({"level": "error", "message": f"Primary provider '{s.primary_provider}' is not configured."})
    if not _provider_configured(s.embedding_provider):
        issues.append({"level": "error", "message": f"Embedding provider '{s.embedding_provider}' is not configured."})
    if integrity["counts"]["repairable_failed_jobs"] > 0:
        issues.append({"level": "warn", "message": "Some failed ingest jobs can be auto-repaired."})
    if graph_status["configured"] and not graph_status["reachable"]:
        issues.append({"level": "warn", "message": "Neo4j is configured but unavailable; SQL graph fallback is active."})
    if redis_status["mode"] == "memory":
        issues.append({"level": "info", "message": "Redis is running in in-memory mode for local development."})
    if qdrant_status["mode"] == "memory":
        issues.append({"level": "info", "message": "Vector store is running in in-memory mode for local development."})

    return {
        "checked_at": datetime.utcnow().isoformat(),
        "runtime_mode": _runtime_mode(),
        "dependencies": {
            "database": db_status,
            "feed": redis_status,
            "vector_store": qdrant_status,
            "graph": graph_status,
            "queue": {
                "mode": "inproc" if redis_status["mode"] == "memory" else "celery-or-inproc",
            },
        },
        "providers": {
            "primary": {
                "name": s.primary_provider,
                "configured": _provider_configured(s.primary_provider),
            },
            "embedding": {
                "name": s.embedding_provider,
                "configured": _provider_configured(s.embedding_provider),
            },
            "fallback": {
                "name": s.fallback_provider or "",
                "configured": _provider_configured(s.fallback_provider) if s.fallback_provider else False,
            },
            "nvidia_key_pool_size": int(bool(s.nvidia_api_key)) + int(bool(s.nvidia_api_key_backup)) + len(
                [k for k in s.nvidia_api_key_backups.split(",") if k.strip()]
            ),
        },
        "automation": {
            "autopilot": autopilot.status(),
            "folder_watcher": folder_watcher.status(),
        },
        "activity": {
            "last_feed_event": last_event,
            "last_feed_event_at_ms": last_event_time,
        },
        "integrity": integrity,
        "issues": issues,
    }
