import json
from io import BytesIO
from urllib.request import Request

from skillproof import ai, config


class MockResponse(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_ai_requires_local_model_configuration(client):
    status = client.get("/api/ai/status")
    assert status.status_code == 200
    assert status.json()["available"] is False
    assert status.json()["configured"] is False
    case_id = client.post("/api/demo").json()["case"]["id"]
    result = client.post(f"/api/cases/{case_id}/ai/analyze", json={"question": "Which institution appears?"})
    assert result.status_code == 503
    assert "SKILLPROOF_OLLAMA_MODEL" in result.json()["detail"]


def test_ai_retrieves_pages_and_discards_fabricated_citations(client, monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_MODEL", "fixture-model")
    case_id = client.post("/api/demo").json()["case"]["id"]
    captured = {}

    def fake_urlopen(request, timeout):
        assert isinstance(request, Request)
        if request.full_url.endswith("/api/tags"):
            return MockResponse(json.dumps({"models": [{"name": "fixture-model"}]}).encode())
        body = json.loads(request.data)
        user_content = json.loads(body["messages"][1]["content"])
        pages = user_content["source_pages"]
        captured["pages"] = pages
        page_id = next(iter(pages))
        quote = "Awarding institution: Alpine Technical Institute"
        return MockResponse(json.dumps({"message": {"content": json.dumps({
            "summary": "One source page states an institution name.",
            "observations": [
                {"page_id": page_id, "quote": quote, "observation": "The source prints this institution name.", "relation": "context"},
                {"page_id": "made-up-page", "quote": "Forged quotation", "observation": "Unsupported", "relation": "supports"},
            ], "uncertainties": ["A text excerpt does not verify a credential."]
        })}}).encode())

    monkeypatch.setattr(ai, "urlopen", fake_urlopen)
    assert client.get("/api/ai/status").json()["available"] is True
    result = client.post(f"/api/cases/{case_id}/ai/analyze", json={"question": "Which awarding institution is printed?"})
    assert result.status_code == 200, result.text
    output = result.json()
    assert output["pages_considered"] >= 1
    assert output["observations"][0]["quote"] == "Awarding institution: Alpine Technical Institute"
    assert output["observations"][0]["page_number"] == 1
    assert output["rejected_citations"] == 1
    assert len(output["observations"]) == 1


def test_ai_requires_case_scoped_current_requirement(client, monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_MODEL", "fixture-model")
    case_id = client.post("/api/demo").json()["case"]["id"]
    result = client.post(f"/api/cases/{case_id}/ai/analyze", json={"question": "Find the institution", "requirement_id": "not-in-case"})
    assert result.status_code == 422
