from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

_settings = get_settings()

celery = Celery(
    "evomind",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)
celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    task_track_started=True,
    task_time_limit=60 * 60,
    task_soft_time_limit=60 * 55,
    worker_prefetch_multiplier=1,
)

# ─── Aggressive autonomous schedule ────────────────────────────────────────
# When Celery+Beat is running (docker compose), these run periodically and
# duplicate the in-process autopilot. The two are safe to run together —
# both share the same DB rows and the LLM calls are idempotent on outcome.
celery.conf.beat_schedule = {
    "autopilot-solve":           {"task": "app.workers.tasks.auto_solve_task",       "schedule":  60.0},  # every 1 min
    "autopilot-seed":            {"task": "app.workers.tasks.auto_seed_task",        "schedule":  60.0},  # every 1 min
    "autopilot-synthesise":      {"task": "app.workers.tasks.auto_synthesise_task",  "schedule": 900.0},  # every 15 min
    "autopilot-hypothesise":     {"task": "app.workers.tasks.auto_hypothesise_task", "schedule": 1800.0}, # every 30 min
    "intelligence-snapshot":     {"task": "app.workers.tasks.snapshot_intelligence_task", "schedule": 300.0}, # every 5 min
    "daily-autonomous-research": {"task": "app.workers.tasks.daily_research_task",   "schedule": crontab(hour=4, minute=0)},
    "daily-backup":              {"task": "app.workers.tasks.daily_backup_task",     "schedule": crontab(hour=3, minute=30)},
}

import app.workers.tasks  # noqa: E402,F401  (registers tasks)
