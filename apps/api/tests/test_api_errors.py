"""Error-path coverage for the HTTP surface — the happy path is covered by
test_smoke.py; here we assert the failure modes behave correctly."""
from __future__ import annotations


def test_get_missing_document_returns_404(client):
    res = client.get("/api/documents/does-not-exist")
    assert res.status_code == 404


def test_delete_missing_document_returns_404(client):
    res = client.delete("/api/documents/does-not-exist")
    assert res.status_code == 404


def test_upload_rejects_non_pdf(client):
    res = client.post(
        "/api/upload",
        files={"file": ("notes.txt", b"not a pdf", "text/plain")},
    )
    assert res.status_code == 400
    assert "pdf" in res.text.lower()


def test_upload_rejects_missing_file(client):
    # No multipart body at all → FastAPI validation error (422).
    res = client.post("/api/upload")
    assert res.status_code == 422


def test_chunks_for_missing_document(client):
    # Querying chunks for a non-existent doc should not 500.
    res = client.get("/api/documents/does-not-exist/chunks")
    assert res.status_code in (200, 404)
