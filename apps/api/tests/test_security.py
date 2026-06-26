"""Tests for the optional API-key auth dependency and upload validation."""
from __future__ import annotations

import pytest
from app.core import security
from app.core.config import get_settings


@pytest.fixture
def auth_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", True)
    monkeypatch.setattr(s, "api_keys", "secret-key-1,secret-key-2")
    yield s


def test_auth_disabled_is_noop():
    # default: auth_enabled False → dependency returns without raising
    assert security.require_api_key(authorization=None, x_api_key=None) is None


def test_valid_bearer_token_passes(auth_on):
    assert security.require_api_key(authorization="Bearer secret-key-1", x_api_key=None) is None


def test_valid_x_api_key_passes(auth_on):
    assert security.require_api_key(authorization=None, x_api_key="secret-key-2") is None


def test_missing_key_rejected(auth_on):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        security.require_api_key(authorization=None, x_api_key=None)
    assert ei.value.status_code == 401


def test_wrong_key_rejected(auth_on):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        security.require_api_key(authorization="Bearer nope", x_api_key=None)
    assert ei.value.status_code == 401


def test_auth_on_without_configured_keys_fails_closed(monkeypatch):
    from fastapi import HTTPException
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", True)
    monkeypatch.setattr(s, "api_keys", "")
    with pytest.raises(HTTPException) as ei:
        security.require_api_key(authorization="Bearer anything", x_api_key=None)
    assert ei.value.status_code == 503


# --- endpoint-level: a protected route enforces auth when enabled ----------

def test_delete_document_requires_key_when_auth_enabled(client, clean_db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "auth_enabled", True)
    monkeypatch.setattr(s, "api_keys", "k1")

    # no key → 401 (auth runs before the 404 lookup)
    assert client.delete("/api/documents/whatever").status_code == 401
    # valid key → passes auth, then 404 for the unknown id
    ok = client.delete("/api/documents/whatever", headers={"X-API-Key": "k1"})
    assert ok.status_code == 404


# --- upload validation ------------------------------------------------------

def test_upload_rejects_non_pdf_content(client, clean_db):
    # .pdf extension but the bytes aren't a PDF (no %PDF header) → 400
    res = client.post(
        "/api/upload",
        files={"file": ("fake.pdf", b"this is not a pdf", "application/pdf")},
    )
    assert res.status_code == 400
    assert "pdf" in res.text.lower()


def test_upload_accepts_pdf_magic(client, clean_db):
    res = client.post(
        "/api/upload",
        files={"file": ("real.pdf", b"%PDF-1.4 minimal body", "application/pdf")},
    )
    # Passes validation and registers a job (ingest itself runs async).
    assert res.status_code == 200
    assert res.json()["document_id"]
