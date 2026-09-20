"""Smoke tests for MineIntel AI API (Phase 1 compatibility).

Uses the shared `client` fixture (isolated in-memory DB) from conftest.
"""


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "MineIntel" in body["app"]


def test_dashboard(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    assert "total_documents" in r.json()


def test_chat(client):
    r = client.post("/api/assistant/chat", json={"message": "Show production summary"})
    assert r.status_code == 200
    assert "reply" in r.json()


def test_documents_list_empty_or_items(client):
    r = client.get("/api/documents")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body
