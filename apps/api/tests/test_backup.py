"""Tests for the backup module + HTTP surface (SQLite path)."""
from __future__ import annotations

from app.modules import backup


def test_create_backup_writes_sqlite_dump_and_manifest(clean_db):
    manifest = backup.create_backup()
    assert manifest["ok"] is True
    db = manifest["components"]["database"]
    assert db["ok"] is True
    assert db["backend"] == "sqlite"

    folder = backup.backup_dir_path() / manifest["id"]
    assert (folder / "database.sqlite").exists()
    assert (folder / "manifest.json").exists()


def test_status_and_list_reflect_created_backup(clean_db):
    before = backup.backup_status()["count"]
    backup.create_backup()
    status = backup.backup_status()
    assert status["count"] == before + 1
    assert status["latest"] is not None
    assert any(b["id"] == status["latest"]["id"] for b in backup.list_backups())


# --- HTTP surface -----------------------------------------------------------

def test_backup_endpoints(client, clean_db):
    created = client.post("/api/backup/now")
    assert created.status_code == 200
    bid = created.json()["id"]

    st = client.get("/api/backup/status")
    assert st.status_code == 200 and st.json()["count"] >= 1

    listing = client.get("/api/backup/list")
    assert listing.status_code == 200
    assert any(b["id"] == bid for b in listing.json())

    dl = client.get(f"/api/backup/{bid}/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/zip"


def test_backup_download_rejects_traversal(client, clean_db):
    assert client.get("/api/backup/..%2f..%2fetc/download").status_code in (400, 404)


def test_backup_download_404_for_unknown(client, clean_db):
    assert client.get("/api/backup/nonexistent/download").status_code == 404
