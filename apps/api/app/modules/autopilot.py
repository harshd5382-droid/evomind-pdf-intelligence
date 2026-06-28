"""Autopilot — continuous in-process research loop.

A single daemon thread that runs while the FastAPI process is alive. It
periodically:

  • seeds questions for any newly-ingested documents that have none yet
  • drains the highest-priority open questions (solve + reflect)
  • synthesises insights from emergent topics
  • generates hypotheses from top insights
  • detects cross-document contradictions
  • refreshes the intelligence snapshot

This means the user only ever has to upload PDFs — every downstream artefact
appears on its own, with no manual "Run Cycle" button click required.

Cadence is controlled by `app.core.config` (`autopilot_*` settings) and can be
disabled by setting `AUTOPILOT_ENABLED=false`.
"""
from __future__ import annotations

import threading
import time
from itertools import combinations

from loguru import logger
from sqlalchemy import asc, func, select

from app.core.config import get_settings
from app.db import postgres, redis_client
from app.db.models import Answer, Document, Question
from app.llm import router as llm

# ────────────────────────────────────────────────────────────────────────────
# Module state — single daemon thread per process
# ────────────────────────────────────────────────────────────────────────────

_thread: threading.Thread | None = None
_stop = threading.Event()
_started_lock = threading.Lock()
_last: dict[str, float] = {}


# ────────────────────────────────────────────────────────────────────────────
# Individual phases — each wrapped in try/except so one failure can't kill the loop
# ────────────────────────────────────────────────────────────────────────────

def _phase_seed_questions() -> int:
    """Generate root questions for unseeded 'ready' documents.

    Bounded per pass — we only seed at most N docs per phase invocation to
    keep within the LLM provider's rate limit. Remaining unseeded docs are
    picked up on the next pass (every `autopilot_seed_interval_sec`). With
    a 60 s cadence and a cap of 4, we sustain ~4 doc-seeds/min indefinitely
    without hammering the API.

    On the first 429 in this pass we stop early — there's no point making
    further calls that will just fail and waste retries.
    """
    from app.modules.questioner.engine import generate_for_document

    s_settings = get_settings()
    cap = max(1, int(s_settings.autopilot_solve_batch))  # tied to solver batch — same budget

    seeded = 0
    seeded_docs = 0

    with postgres.session_scope() as s:
        # Find docs that are ready AND have zero questions, in one query.
        unseeded = s.execute(
            select(Document.id)
            .outerjoin(Question, Question.document_id == Document.id)
            .where(Document.status == "ready")
            .group_by(Document.id)
            .having(func.count(Question.id) == 0)
            .order_by(Document.created_at.desc())
            .limit(cap)
        ).scalars().all()

    for did in unseeded:
        try:
            ids = generate_for_document(did)
            seeded += len(ids)
            seeded_docs += 1
            logger.info("autopilot: seeded {} questions for doc {}", len(ids), did)
        except Exception as e:
            msg = str(e)
            logger.warning("autopilot: seed failed for doc {}: {}", did, msg[:200])
            # On rate-limit, stop the pass immediately. The next phase tick
            # will retry with a fresh budget; pummelling the API just queues
            # more 429s.
            if "429" in msg or "Too Many Requests" in msg:
                logger.info("autopilot: rate-limited during seed — pausing this pass after {} doc(s)", seeded_docs)
                break

    return seeded


def _phase_solve_batch(batch: int) -> list[str]:
    """Solve the top-priority open questions and reflect on each (spawning follow-ups)."""
    from app.modules.learner.engine import reflect_and_expand
    from app.modules.solver.engine import solve_question

    with postgres.session_scope() as s:
        qids = [
            r[0] for r in s.query(Question.id)
            .filter(Question.status == "open")
            .order_by(Question.priority.desc(), asc(Question.created_at))
            .limit(batch)
            .all()
        ]
    if not qids:
        return []

    answer_ids: list[str] = []
    for qid in qids:
        try:
            res = solve_question(qid)
            if res.get("answer_id"):
                answer_ids.append(res["answer_id"])
            try:
                reflect_and_expand(qid, res.get("answer", ""), res.get("confidence", 0.0))
            except Exception as e:
                logger.warning("autopilot: reflect failed q={}: {}", qid, e)
        except Exception as e:
            logger.warning("autopilot: solve failed q={}: {}", qid, e)
    if answer_ids:
        logger.info("autopilot: solved {} questions", len(answer_ids))
    return answer_ids


def _phase_synthesise() -> int:
    """Run cross-document synthesis on the top topics."""
    from app.modules.knowledge.synthesis import synthesize_topic

    with postgres.session_scope() as s:
        docs = s.query(Document).all()
        bag: dict[str, int] = {}
        for d in docs:
            for k in (d.keywords or []):
                bag[k] = bag.get(k, 0) + 1
        subjects = [d.subject_area for d in docs if d.subject_area]

    seen: set[str] = set()
    topics: list[str] = []
    for sub in subjects:
        if sub and sub.lower() not in seen:
            topics.append(sub); seen.add(sub.lower())
    for k, _ in sorted(bag.items(), key=lambda kv: kv[1], reverse=True):
        if k.lower() not in seen and len(topics) < 6:
            topics.append(k); seen.add(k.lower())

    made = 0
    for t in topics[:3]:
        try:
            if synthesize_topic(t):
                made += 1
        except Exception as e:
            logger.warning("autopilot: synthesis on '{}' failed: {}", t, e)
    if made:
        logger.info("autopilot: produced {} insights", made)
    return made


def _phase_hypotheses() -> int:
    from app.modules.knowledge.synthesis import generate_hypotheses_from_top_insights
    try:
        out = generate_hypotheses_from_top_insights() or []
        if out:
            logger.info("autopilot: generated {} hypotheses", len(out))
        return len(out)
    except Exception as e:
        logger.warning("autopilot: hypothesis stage failed: {}", e)
        return 0


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    import math
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def _phase_contradictions(max_pairs: int = 4) -> int:
    """Pick the highest-confidence recent answers and run pairwise contradiction checks."""
    from app.modules.knowledge.synthesis import detect_pairwise_contradiction

    with postgres.session_scope() as s:
        ans = (
            s.query(Answer)
            .filter(Answer.confidence >= 0.55)
            .order_by(Answer.created_at.desc())
            .limit(20)
            .all()
        )

    items = []
    for a in ans:
        cites = a.citations or []
        if not cites:
            continue
        top = cites[0]
        snippet = top.get("snippet") or ""
        if not snippet:
            continue
        items.append({
            "answer_id": a.id, "snippet": snippet,
            "doc": top.get("document_id") or "",
            "chunk": top.get("chunk_id") or "",
        })
    if len(items) < 2:
        return 0

    try:
        vecs = llm.embed([it["snippet"] for it in items])
    except Exception as e:
        logger.warning("autopilot: embed for contradictions failed: {}", e)
        return 0

    candidates: list[tuple[float, int, int]] = []
    for i, j in combinations(range(len(items)), 2):
        if items[i]["doc"] == items[j]["doc"]:
            continue
        sim = _cosine(vecs[i], vecs[j])
        if sim >= 0.55:
            candidates.append((sim, i, j))
    candidates.sort(reverse=True)

    saved = 0
    for _, i, j in candidates[:max_pairs]:
        try:
            cid = detect_pairwise_contradiction(
                items[i]["snippet"], items[j]["snippet"],
                a_chunk_id=items[i]["chunk"], b_chunk_id=items[j]["chunk"],
            )
            if cid:
                saved += 1
        except Exception as e:
            logger.debug("autopilot: contradiction check failed: {}", e)
    if saved:
        logger.info("autopilot: detected {} contradictions", saved)
    return saved


def _phase_score() -> None:
    from app.modules.intelligence.scorer import compute_score
    try:
        compute_score()
    except Exception as e:
        logger.warning("autopilot: score snapshot failed: {}", e)


def _phase_identity() -> None:
    """Recompile the agent's self-model. Cheap (one small LLM call)."""
    from app.modules.identity import update_identity
    try:
        update_identity()
        logger.info("autopilot: identity refreshed")
    except Exception as e:
        logger.warning("autopilot: identity refresh failed: {}", e)


def _phase_memory_backfill() -> None:
    """Embed any memories that don't yet have an embedding."""
    from app.modules.memory import backfill_embeddings
    try:
        n = backfill_embeddings(batch=32)
        if n:
            logger.info("autopilot: backfilled {} memory embeddings", n)
    except Exception as e:
        logger.warning("autopilot: memory backfill failed: {}", e)


def _phase_journal() -> None:
    """Write a first-person reflective journal entry."""
    from app.modules.journal import write_entry
    try:
        write_entry()
    except Exception as e:
        logger.warning("autopilot: journal write failed: {}", e)


def _phase_curiosity() -> None:
    """Recompute knowledge gaps and seed gap-driven questions."""
    from app.modules.curiosity import compute_gaps, seed_gap_questions
    s = get_settings()
    try:
        compute_gaps()
    except Exception as e:
        logger.warning("autopilot: gap computation failed: {}", e)
        return
    # Translate a fraction of the autopilot's solve appetite into gap-driven
    # question creation. With solve_batch=3 and ratio=0.4, we'd seed ~1 new
    # gap question every curiosity tick — feeding the solver fresh material.
    try:
        max_gaps = max(1, int(round(s.autopilot_solve_batch * s.autopilot_curiosity_question_ratio)))
        seed_gap_questions(max_gaps=max_gaps)
    except Exception as e:
        logger.warning("autopilot: gap question seeding failed: {}", e)


# ────────────────────────────────────────────────────────────────────────────
# Loop
# ────────────────────────────────────────────────────────────────────────────

def _due(key: str, interval_sec: float) -> bool:
    now = time.time()
    last = _last.get(key, 0.0)
    if now - last >= interval_sec:
        _last[key] = now
        return True
    return False


def _loop() -> None:
    s = get_settings()
    logger.info(
        "autopilot: engaged "
        "(solve every {}s, synth every {}s, hypoth every {}s, score every {}s)",
        s.autopilot_solve_interval_sec, s.autopilot_synthesis_interval_sec,
        s.autopilot_hypothesis_interval_sec, s.autopilot_score_interval_sec,
    )
    redis_client.publish_event({"type": "autopilot.started"})

    # Initial pass — seed any docs ingested before the server started.
    try:
        _phase_seed_questions()
    except Exception as e:
        logger.warning("autopilot: initial seed failed: {}", e)

    while not _stop.is_set():
        try:
            if _due("seed", s.autopilot_seed_interval_sec):
                _phase_seed_questions()

            if _due("solve", s.autopilot_solve_interval_sec):
                _phase_solve_batch(max(1, s.autopilot_solve_batch))

            if _due("synth", s.autopilot_synthesis_interval_sec):
                _phase_synthesise()

            if _due("hypoth", s.autopilot_hypothesis_interval_sec):
                _phase_hypotheses()

            if _due("contradict", s.autopilot_contradictions_interval_sec):
                _phase_contradictions()

            if _due("score", s.autopilot_score_interval_sec):
                _phase_score()

            # Refresh self-model on the same cadence as the score — both
            # are "snapshots of the agent's current state", and the LLM
            # call here is small.
            if _due("identity", s.autopilot_score_interval_sec):
                _phase_identity()

            # Embed any memory rows that lack an embedding (cheap, batched).
            if _due("memory_backfill", 60):
                _phase_memory_backfill()

            # Phase 4: recompute knowledge gaps + seed curiosity-driven questions
            if _due("curiosity", s.autopilot_curiosity_interval_sec):
                _phase_curiosity()

            # Phase 3: write a first-person journal entry
            if _due("journal", s.autopilot_journal_interval_sec):
                _phase_journal()
        except Exception as e:
            logger.exception("autopilot: iteration crashed (continuing): {}", e)

        # Wake every 5 s to check `_stop` so shutdown is responsive.
        _stop.wait(timeout=5.0)

    logger.info("autopilot: stopped")
    redis_client.publish_event({"type": "autopilot.stopped"})


def start() -> None:
    """Start the autopilot daemon thread (idempotent)."""
    global _thread
    s = get_settings()
    if not s.autopilot_enabled:
        logger.info("autopilot: disabled by config")
        return

    with _started_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(target=_loop, name="evomind-autopilot", daemon=True)
        _thread.start()


def stop(timeout: float = 6.0) -> None:
    """Signal the loop to exit and join (used by FastAPI lifespan shutdown)."""
    _stop.set()
    if _thread and _thread.is_alive():
        _thread.join(timeout=timeout)


def status() -> dict:
    s = get_settings()
    return {
        "enabled": bool(s.autopilot_enabled),
        "running": bool(_thread and _thread.is_alive()),
        "last_runs": dict(_last),
        "intervals": {
            "solve_sec":      s.autopilot_solve_interval_sec,
            "seed_sec":       s.autopilot_seed_interval_sec,
            "synthesis_sec":  s.autopilot_synthesis_interval_sec,
            "hypothesis_sec": s.autopilot_hypothesis_interval_sec,
            "contradict_sec": s.autopilot_contradictions_interval_sec,
            "score_sec":      s.autopilot_score_interval_sec,
            "journal_sec":    s.autopilot_journal_interval_sec,
            "curiosity_sec":  s.autopilot_curiosity_interval_sec,
        },
        "solve_batch": s.autopilot_solve_batch,
    }
