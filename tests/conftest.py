import pytest
from fastapi.testclient import TestClient
from skillproof import config, db, main


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "runtime"
    uploads = data / "uploads"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(config, "DB_PATH", data / "test.sqlite3")
    monkeypatch.setattr(db, "DB_PATH", data / "test.sqlite3")
    monkeypatch.setattr(main, "UPLOAD_DIR", uploads)
    with TestClient(main.app) as test_client:
        yield test_client

