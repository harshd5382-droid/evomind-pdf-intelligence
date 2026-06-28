"""Neo4j wrapper. Optional — when NEO4J_URI is empty or unreachable, every
operation becomes a no-op and graph_snapshot returns empty data."""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.core.config import get_settings

_settings = get_settings()
_driver = None  # type: ignore[var-annotated]
_disabled = False


def _enabled() -> bool:
    return bool(_settings.neo4j_uri) and not _disabled


def driver():
    global _driver, _disabled
    if not _enabled():
        return None
    if _driver is not None:
        return _driver
    try:
        from neo4j import GraphDatabase  # lazy import — neo4j package is optional
        _driver = GraphDatabase.driver(
            _settings.neo4j_uri, auth=(_settings.neo4j_user, _settings.neo4j_password)
        )
        # Lightweight verify — avoid expensive call; rely on first session to surface failures
        return _driver
    except Exception as e:
        logger.warning("Neo4j unavailable ({}); graph features disabled", e)
        _disabled = True
        return None


def upsert_node(label: str, key: str, props: dict[str, Any]) -> None:
    d = driver()
    if d is None:
        return
    cypher = f"MERGE (n:{label} {{id: $id}}) SET n += $props"
    try:
        with d.session() as s:
            s.run(cypher, id=key, props=props)
    except Exception as e:
        logger.debug("Neo4j upsert_node skipped: {}", e)


def upsert_edge(a_label: str, a_id: str, b_label: str, b_id: str, rel: str, props: dict | None = None) -> None:
    d = driver()
    if d is None:
        return
    cypher = (
        f"MATCH (a:{a_label} {{id: $a}}), (b:{b_label} {{id: $b}}) "
        f"MERGE (a)-[r:{rel}]->(b) SET r += $props"
    )
    try:
        with d.session() as s:
            s.run(cypher, a=a_id, b=b_id, props=props or {})
    except Exception as e:
        logger.debug("Neo4j upsert_edge skipped: {}", e)


def graph_snapshot(limit: int = 200) -> dict:
    """Return a graph for the UI. Prefers Neo4j; otherwise derives one from SQL."""
    d = driver()
    if d is None:
        return _graph_from_sql(limit=limit)
    nodes_q = "MATCH (n) RETURN id(n) as nid, labels(n) as labels, n.id as ext, n.name as name, n.title as title LIMIT $limit"
    edges_q = "MATCH (a)-[r]->(b) RETURN id(a) as a, id(b) as b, type(r) as t LIMIT $limit"
    try:
        with d.session() as s:
            nodes = []
            for rec in s.run(nodes_q, limit=limit):
                nodes.append({
                    "id": rec["nid"],
                    "label": (rec["labels"] or ["Node"])[0],
                    "name": rec["name"] or rec["title"] or rec["ext"] or str(rec["nid"]),
                })
            edges = [
                {"source": rec["a"], "target": rec["b"], "type": rec["t"]}
                for rec in s.run(edges_q, limit=limit)
            ]
        if not nodes:
            # Neo4j is up but empty — fall back to SQL so the graph is still useful.
            return _graph_from_sql(limit=limit)
        return {"nodes": nodes, "links": edges}
    except Exception as e:
        logger.debug("Neo4j graph_snapshot failed; using SQL fallback: {}", e)
        return _graph_from_sql(limit=limit)


def _graph_from_sql(limit: int = 200) -> dict:
    """Derive a knowledge graph from data already in Postgres/SQLite.

    Nodes:
      - Paper        (one per Document)
      - Concept      (one per unique keyword across documents)
      - Insight      (one per Insight)
      - Hypothesis   (one per Hypothesis)
      - Contradiction (one per Contradiction)
    Edges:
      - Paper -[MENTIONS]-> Concept       (from Document.keywords)
      - Insight -[SYNTHESIZES]-> Paper    (from Insight.sources document_ids)
      - Contradiction -[INVOLVES]-> Paper (resolved through chunk -> document_id)
      - Hypothesis -[FROM]-> Insight      (chronological proximity heuristic)
    """
    from app.db import postgres
    from app.db.models import Chunk, Contradiction, Document, Hypothesis, Insight

    nodes: list[dict] = []
    links: list[dict] = []
    seen: set[str] = set()

    def add_node(nid: str, label: str, name: str) -> None:
        if nid in seen:
            return
        seen.add(nid)
        nodes.append({"id": nid, "label": label, "name": name[:80]})

    with postgres.session_scope() as s:
        # Papers + Concept fan-out
        docs = list(s.query(Document).all())
        for d in docs:
            add_node(f"paper:{d.id}", "Paper", d.title or d.filename or d.id[:8])
            for kw in (d.keywords or [])[:8]:
                if not isinstance(kw, str) or len(kw) < 3:
                    continue
                cid = f"concept:{kw.lower()}"
                add_node(cid, "Concept", kw)
                links.append({"source": f"paper:{d.id}", "target": cid, "type": "MENTIONS"})

        # Insights and their source documents
        insights = list(s.query(Insight).order_by(Insight.created_at.desc()).limit(40).all())
        for ins in insights:
            add_node(f"insight:{ins.id}", "Insight", ins.title)
            for src in (ins.sources or []):
                doc_id = (src or {}).get("document_id") if isinstance(src, dict) else None
                if doc_id and f"paper:{doc_id}" in seen:
                    links.append({"source": f"insight:{ins.id}", "target": f"paper:{doc_id}", "type": "SYNTHESIZES"})

        # Hypotheses (link each to the nearest insight in time as a soft origin)
        hyps = list(s.query(Hypothesis).order_by(Hypothesis.created_at.desc()).limit(40).all())
        recent_insights_by_time = sorted(insights, key=lambda i: i.created_at)
        for h in hyps:
            add_node(f"hyp:{h.id}", "Hypothesis", h.statement)
            # closest insight before-or-equal h.created_at
            origin = None
            for ins in recent_insights_by_time:
                if ins.created_at <= h.created_at:
                    origin = ins
            if origin is not None:
                links.append({"source": f"hyp:{h.id}", "target": f"insight:{origin.id}", "type": "FROM"})

        # Contradictions resolve to documents via the chunks they reference
        contras = list(s.query(Contradiction).order_by(Contradiction.created_at.desc()).limit(40).all())
        for c in contras:
            add_node(f"contra:{c.id}", "Contradiction", c.summary or "contradiction")
            for chunk_id in (c.a_chunk_id, c.b_chunk_id):
                if not chunk_id:
                    continue
                ch = s.get(Chunk, chunk_id)
                if ch and f"paper:{ch.document_id}" in seen:
                    links.append({"source": f"contra:{c.id}", "target": f"paper:{ch.document_id}", "type": "INVOLVES"})

    # Trim to limit and drop edges whose endpoints didn't make the cut
    nodes = nodes[:limit]
    keep = {n["id"] for n in nodes}
    links = [lk for lk in links if lk["source"] in keep and lk["target"] in keep]
    return {"nodes": nodes, "links": links, "source": "sql"}


def status() -> dict:
    if not _settings.neo4j_uri:
        return {
            "configured": False,
            "mode": "disabled",
            "reachable": False,
            "error": None,
        }

    d = driver()
    if d is None:
        return {
            "configured": True,
            "mode": "neo4j",
            "reachable": False,
            "error": "connection unavailable",
        }

    try:
        with d.session() as s:
            s.run("RETURN 1").single()
        return {
            "configured": True,
            "mode": "neo4j",
            "reachable": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "configured": True,
            "mode": "neo4j",
            "reachable": False,
            "error": str(exc),
        }
