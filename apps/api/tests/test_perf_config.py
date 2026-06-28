"""Tests for Phase 7: question-tree fix, metrics cache, batch cosine, config write."""
from __future__ import annotations

from app.core.config import get_settings
from app.db import postgres
from app.db.models import Question


def test_question_tree_builds_nested_levels(client, clean_db):
    with postgres.session_scope() as s:
        s.add(Question(id="r", text="root", category="understanding", status="open", depth=0))
        s.add(Question(id="c1", text="child1", category="meta", status="open", parent_id="r", depth=1))
        s.add(Question(id="c2", text="child2", category="meta", status="open", parent_id="r", depth=1))
        s.add(Question(id="g1", text="grand", category="meta", status="open", parent_id="c1", depth=2))

    tree = client.get("/api/questions/r/tree").json()
    assert tree["id"] == "r"
    assert {c["id"] for c in tree["children"]} == {"c1", "c2"}
    c1 = next(c for c in tree["children"] if c["id"] == "c1")
    assert c1["children"][0]["id"] == "g1"


def test_question_tree_404(client, clean_db):
    assert client.get("/api/questions/nope/tree").status_code == 404


def test_batch_cosine_matches_scalar():
    from app.modules.memory.store import _batch_cosine, _cosine

    q = [1.0, 0.0, 0.0]
    vecs = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 1.0, 0.0], None, [1.0, 0.0]]
    batch = _batch_cosine(q, vecs)
    assert abs(batch[0] - 1.0) < 1e-5
    assert abs(batch[1] - 0.0) < 1e-5
    assert abs(batch[2] - _cosine(q, [1.0, 1.0, 0.0])) < 1e-5
    assert batch[3] == 0.0  # None
    assert batch[4] == 0.0  # dim mismatch


def test_metrics_cache_serves_repeated_calls(client, clean_db):
    from app.api import routes
    routes._metrics_payload.cache_clear()
    a = client.get("/api/metrics").json()
    b = client.get("/api/metrics").json()
    assert a == b  # second call served from the TTL cache


def test_update_config_changes_runtime_knobs(client, clean_db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "creativity", 0.5)
    res = client.post("/api/config", json={"creativity": 0.9, "autonomy_level": "cautious"})
    assert res.status_code == 200
    body = res.json()
    assert body["changed"]["creativity"] == 0.9
    assert get_settings().creativity == 0.9
    assert get_settings().autonomy_level == "cautious"


def test_update_config_rejects_out_of_range(client, clean_db):
    assert client.post("/api/config", json={"creativity": 5}).status_code == 422
