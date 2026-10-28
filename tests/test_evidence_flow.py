from __future__ import annotations

import io
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from skillproof import config, db, main, processing


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "runtime"
    uploads = data / "uploads"
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(config, "DB_PATH", data / "test.sqlite3")
    monkeypatch.setattr(db, "DB_PATH", data / "test.sqlite3")
    monkeypatch.setattr(processing, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(main, "UPLOAD_DIR", uploads)
    with TestClient(main.app) as test_client:
        yield test_client


def pdf_bytes(text: str, page_count: int = 1) -> bytes:
    writer = PdfWriter()
    pages = [writer.add_blank_page(width=612, height=792) for _ in range(page_count)]
    page = pages[0]
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})})
    page[NameObject("/MediaBox")] = page.mediabox
    lines = text.splitlines() or [text]
    commands = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({safe}) Tj")
        if index < len(lines) - 1:
            commands.append("0 -16 Td")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def wait_job(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        result = client.get(f"/api/jobs/{job_id}").json()
        if result["state"] in {"complete", "failed"}:
            return result
        time.sleep(0.025)
    raise AssertionError("Document processing did not finish within the test deadline")


def test_local_pdf_to_human_review_and_export(client):
    case = client.post("/api/cases", json={"title": "Synthetic test case", "occupation": "Technician"})
    assert case.status_code == 201
    case_id = case.json()["case"]["id"]
    requirement = client.post(f"/api/cases/{case_id}/requirements", json={
        "title": "Certificate and award date", "source_name": "Synthetic checklist", "source_checked_at": "2026-10-28", "guidance": "Synthetic-only test requirement."
    })
    assert requirement.status_code == 201
    requirement_id = requirement.json()["id"]

    upload = client.post(f"/api/cases/{case_id}/documents", files={"file": ("certificate.pdf", pdf_bytes("Award: Diploma in Energy Systems\nInstitution: Example Institute\nAward date: 2019"), "application/pdf")})
    assert upload.status_code == 202
    result = wait_job(client, upload.json()["job_id"])
    assert result["state"] == "complete"

    document_id = upload.json()["document_id"]
    detail = client.get(f"/api/documents/{document_id}/pages/1")
    assert detail.status_code == 200
    page = detail.json()
    assert "Award: Diploma in Energy Systems" in page["text"]
    assert page["regions"]
    suggestion = next(item for item in page["suggestions"] if item["claim_text"] == "Award: Diploma in Energy Systems")
    assert suggestion["region_id"]

    invalid_region = client.post(f"/api/cases/{case_id}/evidence", json={
        "requirement_id": requirement_id, "document_id": document_id, "page_number": 1,
        "claim_text": "Award: Diploma in Energy Systems", "region_id": "not-on-this-page", "provenance": "human_observed"
    })
    assert invalid_region.status_code == 422

    evidence = client.post(f"/api/cases/{case_id}/evidence", json={
        "requirement_id": requirement_id,
        "document_id": document_id,
        "page_number": 1,
        "claim_type": "qualification",
        "claim_text": "Award: Diploma in Energy Systems",
        "region_id": suggestion["region_id"],
        "provenance": "human_observed",
    })
    assert evidence.status_code == 201
    assert evidence.json()["provenance"] == "human_observed"
    reviewed = client.patch(f"/api/evidence/{evidence.json()['id']}", json={"disposition": "supports", "reviewer_note": "Checked against synthetic source page."})
    assert reviewed.status_code == 200
    assert reviewed.json()["provenance"] == "human_verified"

    revised = client.put(f"/api/requirements/{requirement_id}", json={
        "title": "Certificate and award date", "source_name": "Updated synthetic checklist", "source_checked_at": "2026-10-29", "guidance": "Rechecked in the synthetic test."
    })
    assert revised.status_code == 201
    assert revised.json()["version"] == 2
    history = client.get(f"/api/requirements/{revised.json()['id']}/history")
    assert history.status_code == 200
    assert [version["version"] for version in history.json()] == [1, 2]
    current = client.get(f"/api/cases/{case_id}").json()
    assert current["requirements"][0]["version"] == 2
    assert current["evidence"][0]["requirement_version"] == 1

    packet = client.get(f"/api/cases/{case_id}/packet.md")
    assert packet.status_code == 200
    assert "Award: Diploma in Energy Systems" in packet.text
    assert "Page | Provenance" in packet.text
    assert "v1 · Certificate and award date" in packet.text
    assert "does not verify authenticity" in packet.text


def test_duplicate_upload_is_rejected_and_case_delete_removes_file(client, tmp_path):
    case_id = client.post("/api/cases", json={"title": "Deletion test"}).json()["case"]["id"]
    pdf = pdf_bytes("Synthetic record\nAward: Example certificate")
    first = client.post(f"/api/cases/{case_id}/documents", files={"file": ("one.pdf", pdf, "application/pdf")})
    assert first.status_code == 202
    wait_job(client, first.json()["job_id"])
    duplicate = client.post(f"/api/cases/{case_id}/documents", files={"file": ("copy.pdf", pdf, "application/pdf")})
    assert duplicate.status_code == 409
    detail = client.get(f"/api/cases/{case_id}").json()
    assert len(detail["documents"]) == 1
    stored = list((tmp_path / "runtime" / "uploads").iterdir())
    assert len(stored) == 1
    deleted = client.delete(f"/api/cases/{case_id}")
    assert deleted.status_code == 204
    assert not list((tmp_path / "runtime" / "uploads").iterdir())


def test_evidence_quote_must_be_on_selected_page(client):
    case_id = client.post("/api/cases", json={"title": "Citation test"}).json()["case"]["id"]
    upload = client.post(f"/api/cases/{case_id}/documents", files={"file": ("record.pdf", pdf_bytes("Name: Fictional Person"), "application/pdf")})
    wait_job(client, upload.json()["job_id"])
    response = client.post(f"/api/cases/{case_id}/evidence", json={
        "document_id": upload.json()["document_id"], "page_number": 1, "claim_text": "A qualification was recognized", "provenance": "human_observed"
    })
    assert response.status_code == 422


def test_synthetic_demo_is_marked_and_discrepancy_is_only_a_prompt(client):
    response = client.post("/api/demo")
    assert response.status_code == 201
    case_id = response.json()["case"]["id"]
    details = client.get(f"/api/cases/{case_id}").json()
    assert all("Synthetic" in d["original_name"] or d["original_name"].startswith("synthetic-") for d in details["documents"])
    checks = client.get(f"/api/cases/{case_id}/checks").json()
    assert "not establish" in checks["notice"]
    assert any(item["field"] == "institution" for item in checks["potential_discrepancies"])


def test_bad_file_signature_and_security_headers(client):
    case_id = client.post("/api/cases", json={"title": "Input test"}).json()["case"]["id"]
    response = client.post(f"/api/cases/{case_id}/documents", files={"file": ("fake.pdf", io.BytesIO(b"not a pdf"), "application/pdf")})
    assert response.status_code == 415
    page = client.get("/")
    assert page.status_code == 200
    assert page.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in page.headers["content-security-policy"]
    cross_origin = client.post("/api/cases", headers={"Origin": "https://example.invalid"}, json={"title": "Must be blocked"})
    assert cross_origin.status_code == 403


def test_whitespace_table_candidates_are_marked_as_heuristic():
    from skillproof.processing import _layout_tables

    tables = _layout_tables("Year     Course             Result\n2019     Electrical safety  Pass\n2020     Energy systems     Pass", 3)
    assert len(tables) == 1
    assert tables[0]["method"] == "whitespace-layout heuristic"
    assert tables[0]["review_required"] is True


def test_multi_batch_pdf_processing_persists_late_pages(client):
    case_id = client.post("/api/cases", json={"title": "Multi-page synthetic case"}).json()["case"]["id"]
    upload = client.post(f"/api/cases/{case_id}/documents", files={"file": ("large-synthetic.pdf", pdf_bytes("Award: Diploma in Energy Systems", page_count=63), "application/pdf")})
    assert upload.status_code == 202
    result = wait_job(client, upload.json()["job_id"])
    assert result["state"] == "complete"
    document = client.get(f"/api/cases/{case_id}").json()["documents"][0]
    assert document["page_count"] == 63
    last_page = client.get(f"/api/documents/{document['id']}/pages/63")
    assert last_page.status_code == 200
    assert last_page.json()["page_number"] == 63


def test_first_prototype_database_gets_requirement_history_columns(tmp_path, monkeypatch):
    data = tmp_path / "legacy-runtime"
    data.mkdir()
    database = data / "legacy.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("""CREATE TABLE requirements (
            id TEXT PRIMARY KEY, case_id TEXT NOT NULL, code TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL, guidance TEXT NOT NULL DEFAULT '', source_name TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '', source_checked_at TEXT NOT NULL DEFAULT '',
            required INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)""")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "UPLOAD_DIR", data / "uploads")
    monkeypatch.setattr(config, "DB_PATH", database)
    monkeypatch.setattr(db, "DB_PATH", database)
    db.initialize()
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(requirements)")}
    assert {"version", "supersedes_id", "is_current"}.issubset(columns)
