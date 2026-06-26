from datetime import datetime

from loguru import logger

from app.db import postgres
from app.db.models import Job
from app.ingestion.pipeline import ingest_pdf
from app.modules.intelligence.scorer import compute_score
from app.modules.orchestrator import run_cycle, run_daily_research
from app.workers.celery_app import celery


def _start_job(job_id: str) -> None:
    with postgres.session_scope() as s:
        j = s.get(Job, job_id)
        if j:
            j.status = "running"
            j.started_at = datetime.utcnow()


def _finish_job(job_id: str, status: str = "succeeded", detail: str = "") -> None:
    with postgres.session_scope() as s:
        j = s.get(Job, job_id)
        if j:
            j.status = status
            j.detail = detail or j.detail
            j.progress = 1.0
            j.finished_at = datetime.utcnow()


@celery.task(name="app.workers.tasks.ingest_task")
def ingest_task(file_path: str, document_id: str | None = None, job_id: str | None = None) -> dict:
    if job_id:
        _start_job(job_id)
    try:
        doc_id = ingest_pdf(file_path, document_id=document_id)
        if job_id:
            _finish_job(job_id, "succeeded", f"document_id={doc_id}")
        return {"document_id": doc_id}
    except Exception as e:
        logger.exception("Ingest failed: {}", e)
        if job_id:
            _finish_job(job_id, "failed", str(e))
        raise


@celery.task(name="app.workers.tasks.cycle_task")
def cycle_task(question_budget: int = 8, job_id: str | None = None) -> dict:
    if job_id:
        _start_job(job_id)
    try:
        summary = run_cycle(question_budget=question_budget)
        if job_id:
            _finish_job(job_id, "succeeded", str(summary)[:500])
        return summary
    except Exception as e:
        logger.exception("Cycle failed: {}", e)
        if job_id:
            _finish_job(job_id, "failed", str(e))
        raise


@celery.task(name="app.workers.tasks.daily_research_task")
def daily_research_task() -> dict:
    return run_daily_research()


@celery.task(name="app.workers.tasks.snapshot_intelligence_task")
def snapshot_intelligence_task() -> dict:
    return compute_score()


# ─── Autopilot tasks (periodic, idempotent) ───────────────────────────────
@celery.task(name="app.workers.tasks.auto_seed_task")
def auto_seed_task() -> dict:
    from app.modules.autopilot import _phase_seed_questions
    return {"seeded": _phase_seed_questions()}


@celery.task(name="app.workers.tasks.auto_solve_task")
def auto_solve_task(batch: int | None = None) -> dict:
    from app.core.config import get_settings
    from app.modules.autopilot import _phase_solve_batch
    s = get_settings()
    n = batch or max(1, s.autopilot_solve_batch)
    answer_ids = _phase_solve_batch(n)
    return {"solved": len(answer_ids), "answer_ids": answer_ids}


@celery.task(name="app.workers.tasks.auto_synthesise_task")
def auto_synthesise_task() -> dict:
    from app.modules.autopilot import _phase_synthesise
    return {"insights": _phase_synthesise()}


@celery.task(name="app.workers.tasks.auto_hypothesise_task")
def auto_hypothesise_task() -> dict:
    from app.modules.autopilot import _phase_hypotheses
    return {"hypotheses": _phase_hypotheses()}
