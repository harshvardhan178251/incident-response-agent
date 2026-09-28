"""API flow test: create -> investigate -> resolve, Hindsight stubbed, LLM heuristic."""
import pytest
from fastapi.testclient import TestClient

import llm
import memory
import store


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "incidents.json")
    monkeypatch.setattr(llm, "LLM_OFFLINE", True)

    async def fake_recall(query, top_k=5):
        return {"available": True, "memories": [
            {"rank": 1, "text": "Incident INC-001 | Service: Payment API | Resolution: Increase pool | Outcome: SUCCESS",
             "scores": {"final": 1.1, "semantic": 0.8, "keyword": 0.9},
             "incident_id": "INC-001", "occurred_start": "",
             "metadata": {"incident_id": "INC-001", "service": "Payment API",
                          "outcome": "SUCCESS", "resolution": "Increase pool"},
             "tags": [], "service": "Payment API", "outcome": "SUCCESS",
             "resolution": "Increase pool"},
            {"rank": 2, "text": "Incident INC-002 | Service: Payment API | Resolution: Restart | Outcome: FAILED",
             "scores": {"final": 0.5, "semantic": 0.4, "keyword": 0.3},
             "incident_id": "INC-002", "occurred_start": "",
             "metadata": {"incident_id": "INC-002", "service": "Payment API",
                          "outcome": "FAILED", "resolution": "Restart"},
             "tags": [], "service": "Payment API", "outcome": "FAILED",
             "resolution": "Restart"},
        ]}

    async def fake_retain(**kwargs):
        return {"retained": True, "memory_id": "mem-test-1"}

    async def fake_reachable():
        return True

    monkeypatch.setattr(memory, "recall_memories", fake_recall)
    monkeypatch.setattr(memory, "retain_memory", fake_retain)
    monkeypatch.setattr(memory, "hindsight_reachable", fake_reachable)

    import main
    return TestClient(main.app)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["memory_backend"] == "hindsight"


def test_version(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    assert "version" in r.json()


def test_full_learning_loop(client):
    c = client.post("/api/incidents", json={
        "service": "Payment API", "severity": "Critical",
        "error_logs": "HTTP 503\nRedis timeout\nconnection pool exhausted"})
    assert c.status_code == 201
    iid = c.json()["id"]

    i = client.post(f"/api/incidents/{iid}/investigate", json={})
    assert i.status_code == 200
    body = i.json()
    assert "Redis" in body["root_cause"]
    assert body["fingerprint"]["dependency"] == "Redis"
    assert len(body["memories"]) == 2
    assert body["memory_impact"]["n"] == 2
    assert len(body["failed_fixes"]) == 1
    assert body["recommendation_structured"]["resembles_incident_id"] == "INC-001"
    assert body["confidence"]["confidence"] is not None

    r = client.post(f"/api/incidents/{iid}/resolve",
                    json={"resolution": "Increased Redis pool", "outcome": "SUCCESS"})
    assert r.status_code == 200
    assert "Memory Updated" in r.json()["message"]
    assert r.json()["runbook"]["source_incident"] == iid
