"""Settings and serving used by the AWS image."""

from __future__ import annotations

from fastapi.testclient import TestClient

from wealth.api.main import create_app
from wealth.config import get_settings


def test_database_url_built_from_rds_parts(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("DB_HOST", "db.example.internal")
    monkeypatch.setenv("DB_USER", "wealth_admin")
    monkeypatch.setenv("DB_PASSWORD", "p@ss:w/rd?#")
    monkeypatch.setenv("DB_NAME", "wealth")
    get_settings.cache_clear()
    url = get_settings().database_url
    assert (
        url
        == "postgresql://wealth_admin:p%40ss%3Aw%2Frd%3F%23@db.example.internal:5432/wealth?sslmode=require"
    )


def test_frontend_served_with_spa_fallback(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<app-root></app-root>")
    (tmp_path / "main-abc.js").write_text("console.log(1)")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    with TestClient(create_app()) as c:
        assert c.get("/main-abc.js").text == "console.log(1)"
        assert "immutable" in c.get("/main-abc.js").headers["cache-control"]
        deep = c.get("/advisor/accounts?client=10")  # Angular route -> index.html
        assert deep.text == "<app-root></app-root>" and deep.headers["cache-control"] == "no-cache"
        assert c.get("/api/does-not-exist").status_code == 404  # API paths never fall back
        assert c.get("/../../etc/passwd").text == "<app-root></app-root>"  # no escaping the folder
