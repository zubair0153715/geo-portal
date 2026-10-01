"""Report download option: ?download=1 serves the report HTML as an attachment.

View (no param) still renders inline. Auth guards: only the owning business's
files, only for the logged-in owner.
"""

import os

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "DEMO_MODE", False)
    monkeypatch.setattr(config, "SESSION_SECRET", "test-session-secret")
    db.init_db()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/signup", data={"email": "owner@example.com", "password": "secret123"})
    assert r.status_code in (200, 303)
    uid = db.get_user_by_email("owner@example.com")["id"]
    biz = db.create_business(uid, "Biz", "https://biz.example.com", ["p1"])
    fname = f"report_{biz}_2026-10-01_test.html"
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    path = os.path.join(config.REPORTS_DIR, fname)
    with open(path, "w") as f:
        f.write("<html><body>test report</body></html>")
    db.insert_report(biz, path)
    yield c, biz, fname, path
    if os.path.isfile(path):
        os.remove(path)


def _get(client, biz, fname, download=0):
    return client.get(
        f"/reports/files/{fname}?business_id={biz}" + ("&download=1" if download else "")
    )


def test_view_renders_inline(client):
    c, biz, fname, _ = client
    r = _get(c, biz, fname)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "attachment" not in r.headers.get("content-disposition", "")
    assert b"test report" in r.content


def test_download_returns_attachment(client):
    c, biz, fname, _ = client
    r = _get(c, biz, fname, download=1)
    assert r.status_code == 200
    cd = r.headers.get("content-disposition", "")
    assert "attachment" in cd and fname in cd
    assert b"test report" in r.content


def test_other_business_file_rejected(client):
    c, biz, fname, _ = client
    r = c.get(f"/reports/files/report_99999_x.html?business_id={biz}&download=1")
    assert r.status_code == 404


def test_requires_login(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "anon.db"))
    monkeypatch.setattr(config, "DEMO_MODE", False)
    monkeypatch.setattr(config, "SESSION_SECRET", "test-session-secret")
    db.init_db()
    anon = TestClient(app, raise_server_exceptions=False)
    r = anon.get("/reports/files/report_1_x.html?business_id=1&download=1",
                 follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307)
