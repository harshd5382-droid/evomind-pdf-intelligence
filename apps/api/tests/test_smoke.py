import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

tmp = tempfile.TemporaryDirectory()
tmp_root = tmp.name
os.environ.setdefault("POSTGRES_DSN", f"sqlite:///{os.path.join(tmp_root, 'smoke.db')}")
os.environ.setdefault("REDIS_URL", "memory://")
os.environ.setdefault("QDRANT_URL", "memory://")
os.environ.setdefault("NEO4J_URI", "")
os.environ.setdefault("DATA_DIR", tmp_root)
os.environ.setdefault("UPLOAD_DIR", os.path.join(tmp_root, "uploads"))
os.environ.setdefault("AUTOPILOT_ENABLED", "false")
os.environ.setdefault("AUTO_INGEST_ENABLED", "false")
os.environ.setdefault("PRIMARY_PROVIDER", "ollama")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")

from fastapi.testclient import TestClient

from app.db import postgres, redis_client
from app.db.models import Answer, Chunk, Contradiction, Document, Hypothesis, Insight, Job, Memory, Question, Usage
from app.main import create_app


class SmokeApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        postgres.init_db()
        with postgres.session_scope() as s:
            doc = Document(
                id="doc-1",
                title="Smoke Document",
                filename="smoke.pdf",
                path=os.path.join(tmp_root, "smoke.pdf"),
                page_count=2,
                subject_area="testing",
                importance=0.7,
                keywords=["testing", "stability"],
                status="ready",
            )
            s.add(doc)
            s.add(Chunk(id="chunk-1", document_id=doc.id, ord=0, page=1, text="hello world"))
            q = Question(
                id="q-1",
                text="What does the smoke doc say?",
                category="understanding",
                document_id=doc.id,
                status="answered",
                priority=0.9,
            )
            s.add(q)
            s.add(Answer(id="a-1", question_id=q.id, text="It says hello world.", confidence=0.8))
            ins = Insight(id="ins-1", title="Smoke Insight", body="A stable insight.", kind="synthesis", sources=[{"document_id": doc.id}])
            s.add(ins)
            hyp = Hypothesis(id="hyp-1", statement="Smoke systems stay green.", rationale="seeded", testable=True)
            s.add(hyp)
            s.add(Contradiction(id="con-1", summary="No contradiction", severity=0.1))
            s.add(Memory(id="mem-1", layer="long", content="Remember the smoke test.", importance=0.8, source_kind="insight", source_id=ins.id, embedding=[0.1, 0.2, 0.3]))
            s.add(Job(id="job-1", kind="ingest", target_id=doc.id, status="succeeded", detail="done"))
            s.add(Usage(provider="ollama", model="qwen", purpose="solver", input_tokens=10, output_tokens=5, latency_ms=42))
        redis_client.publish_event({"type": "document.ingested", "document_id": "doc-1", "title": "Smoke Document"})
        cls.client = TestClient(create_app())

    @classmethod
    def tearDownClass(cls):
        postgres.engine.dispose()
        tmp.cleanup()

    def test_core_get_endpoints(self):
        for path in (
            "/api/health",
            "/api/diagnostics",
            "/api/documents",
            "/api/documents/doc-1",
            "/api/documents/doc-1/chunks",
            "/api/documents/doc-1/questions",
            "/api/questions",
            "/api/questions/q-1/answers",
            "/api/questions/q-1/tree",
            "/api/insights",
            "/api/memory",
            "/api/memory/stats",
            "/api/hypotheses",
            "/api/contradictions",
            "/api/graph",
            "/api/metrics",
            "/api/usage/summary?hours=24",
            "/api/jobs/stats",
            "/api/feed/recent?limit=5",
            "/api/autopilot/status",
            "/api/folder-watcher/status",
        ):
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, path)

    def test_integrity_and_repair_endpoints(self):
        res = self.client.get("/api/integrity")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("counts", body)

        repair = self.client.post("/api/integrity/repair")
        self.assertEqual(repair.status_code, 200)
        self.assertIn("repairs", repair.json())

    def test_autonomous_cycle_fallback_path(self):
        fake_tasks = SimpleNamespace(cycle_task=SimpleNamespace(delay=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("no broker"))))
        with patch.dict(sys.modules, {"app.workers.tasks": fake_tasks}):
            with patch("app.modules.orchestrator.run_cycle", return_value={"ok": True, "question_budget": 1}):
                res = self.client.post("/api/run-autonomous-cycle", json={"question_budget": 1})
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["queued"])
        self.assertEqual(res.json()["summary"]["ok"], True)


if __name__ == "__main__":
    unittest.main()
