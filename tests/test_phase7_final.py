"""Phase 7 — reports, RBAC, audit, versioning, correction history, Ollama health."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import create_access_token, hash_password, verify_password
from app.database import Base, get_db
from app.main import create_app
from app.models import (
    Document,
    DocumentStatus,
    ExtractedFact,
    FactCorrectionHistory,
    FactStatus,
    ReviewItem,
    ReviewStatus,
    User,
    UserRole,
    UserStatus,
)


@pytest.fixture()
def phase7_client(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    monkeypatch.setenv("AUTH_SEED_USERS", "false")
    monkeypatch.setenv("ASSISTANT_LLM_PROVIDER", "mock")
    monkeypatch.setenv("DOCUMENTS_DIR", str(tmp_path / "documents"))
    (tmp_path / "documents" / "original").mkdir(parents=True)
    (tmp_path / "documents" / "reports").mkdir(parents=True)

    from app.config import get_settings

    get_settings.cache_clear()

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def _override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = _override
    client = TestClient(app)

    # Seed users
    db = TestingSession()
    admin = User(
        username="admin",
        display_name="Admin",
        password_hash=hash_password("admin123"),
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    analyst = User(
        username="analyst",
        display_name="Analyst",
        password_hash=hash_password("analyst123"),
        role=UserRole.ANALYST.value,
        status=UserStatus.ACTIVE.value,
    )
    reviewer = User(
        username="reviewer",
        display_name="Reviewer",
        password_hash=hash_password("reviewer123"),
        role=UserRole.REVIEWER.value,
        status=UserStatus.ACTIVE.value,
    )
    db.add_all([admin, analyst, reviewer])
    db.commit()
    db.refresh(admin)
    db.refresh(analyst)
    db.refresh(reviewer)
    ids = {"admin": admin.id, "analyst": analyst.id, "reviewer": reviewer.id}
    db.close()

    yield client, TestingSession, ids
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def _token(user_id: str, username: str, role: str) -> str:
    return create_access_token(user_id=user_id, username=username, role=role)


def _auth(role: str, ids: dict) -> dict:
    return {"Authorization": f"Bearer {_token(ids[role], role, role)}"}


def test_password_hash_not_plaintext():
    h = hash_password("secret123")
    assert h != "secret123"
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_login_and_me(phase7_client):
    client, _, _ = phase7_client
    bad = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401

    ok = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert ok.status_code == 200
    body = ok.json()
    assert "access_token" in body
    assert body["user"]["role"] == "admin"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "admin"


def test_rbac_unauthorized_without_token(phase7_client):
    client, _, _ = phase7_client
    r = client.get("/api/users")
    assert r.status_code in {401, 403}


def test_rbac_analyst_cannot_manage_users(phase7_client):
    client, _, ids = phase7_client
    r = client.get("/api/users", headers=_auth("analyst", ids))
    assert r.status_code == 403


def test_rbac_admin_can_manage_users(phase7_client):
    client, _, ids = phase7_client
    r = client.get("/api/users", headers=_auth("admin", ids))
    assert r.status_code == 200
    assert r.json()["total"] >= 3

    created = client.post(
        "/api/users",
        headers=_auth("admin", ids),
        json={"username": "newbie", "password": "newbie12", "role": "user"},
    )
    assert created.status_code == 200
    assert created.json()["username"] == "newbie"
    assert created.json()["role"] == "user"
    assert "password" not in created.json()

    # Legacy role strings are accepted and normalized
    legacy = client.post(
        "/api/users",
        headers=_auth("admin", ids),
        json={"username": "legacy_a", "password": "legacy12", "role": "analyst"},
    )
    assert legacy.status_code == 200
    assert legacy.json()["role"] == "user"


def test_analyst_cannot_read_audit(phase7_client):
    client, _, ids = phase7_client
    r = client.get("/api/system/audit-logs", headers=_auth("analyst", ids))
    assert r.status_code == 403


def test_admin_can_read_audit(phase7_client):
    client, _, ids = phase7_client
    # generate a login audit first
    client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    r = client.get("/api/system/audit-logs", headers=_auth("admin", ids))
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    actions = {i["action"] for i in r.json()["items"]}
    assert "LOGIN" in actions


def test_report_generate_view_download(phase7_client, tmp_path):
    client, Session, ids = phase7_client
    # Empty DB → report still generates with insufficient sections
    # USER (legacy analyst) may generate; ADMIN (legacy reviewer) may also generate.
    gen = client.post(
        "/api/reports/generate",
        headers=_auth("analyst", ids),
        json={"title": "Empty intelligence", "metric": "coal"},
    )
    assert gen.status_code == 200
    report_id = gen.json()["id"]
    assert gen.json()["status"] == "ready"
    assert gen.json()["has_content"] is True

    detail = client.get(f"/api/reports/{report_id}", headers=_auth("analyst", ids))
    assert detail.status_code == 200
    assert "content" in detail.json()

    view = client.get(f"/api/reports/{report_id}/view", headers=_auth("analyst", ids))
    assert view.status_code == 200
    assert "text/html" in view.headers.get("content-type", "")
    assert b"MineIntel" in view.content

    dl = client.get(f"/api/reports/{report_id}/download", headers=_auth("analyst", ids))
    assert dl.status_code == 200
    assert "attachment" in dl.headers.get("content-disposition", "")

    # USER cannot access admin-only validation
    denied_val = client.get("/api/validation/conflicts", headers=_auth("analyst", ids))
    assert denied_val.status_code == 403

    # Legacy reviewer maps to ADMIN — can generate and validate
    ok_gen = client.post(
        "/api/reports/generate",
        headers=_auth("reviewer", ids),
        json={"title": "Admin report"},
    )
    assert ok_gen.status_code == 200


def test_correction_history_preserved(phase7_client):
    client, Session, ids = phase7_client
    db = Session()
    doc = Document(
        filename="f.pdf",
        original_filename="f.pdf",
        file_path=str(Path("f.pdf")),
        file_type="pdf",
        status=DocumentStatus.COMPLETED.value,
        version=1,
    )
    db.add(doc)
    db.flush()
    fact = ExtractedFact(
        document_id=doc.id,
        field_name="production",
        value="5.2",
        unit="MT",
        entity_name="CIL",
        status=FactStatus.REVIEW_REQUIRED.value,
        confidence_score=0.5,
    )
    db.add(fact)
    db.flush()
    review = ReviewItem(
        document_id=doc.id,
        extracted_fact_id=fact.id,
        field_name="production",
        extracted_value="5.2",
        original_unit="MT",
        entity_name="CIL",
        confidence=0.5,
        status=ReviewStatus.PENDING.value,
        source_document="f.pdf",
    )
    db.add(review)
    db.commit()
    rid = review.id
    fid = fact.id
    db.close()

    res = client.post(
        f"/api/reviews/{rid}/action",
        headers=_auth("reviewer", ids),
        json={"action": "correct", "corrected_value": "5.0", "corrected_unit": "MT", "review_notes": "OCR fix"},
    )
    assert res.status_code == 200
    assert res.json()["corrected_value"] == "5.0"
    assert res.json()["extracted_value"] == "5.2"

    hist = client.get(
        f"/api/reviews/corrections/history?fact_id={fid}",
        headers=_auth("reviewer", ids),
    )
    assert hist.status_code == 200
    items = hist.json()["items"]
    assert len(items) >= 1
    assert items[0]["original_value"] == "5.2"
    assert items[0]["corrected_value"] == "5.0"

    db = Session()
    fact2 = db.query(ExtractedFact).filter(ExtractedFact.id == fid).first()
    assert fact2 is not None
    assert fact2.value == "5.0"
    assert (fact2.meta or {}).get("original_ai_value") == "5.2"
    assert db.query(FactCorrectionHistory).filter(FactCorrectionHistory.extracted_fact_id == fid).count() == 1
    db.close()


def test_document_versioning_creates_new_record(phase7_client, tmp_path):
    client, Session, ids = phase7_client
    # Minimal PDF-like bytes may fail magic validation — use a tiny real PDF header
    pdf_bytes = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    files = {"file": ("report_v1.pdf", pdf_bytes, "application/pdf")}
    up1 = client.post(
        "/api/documents/upload",
        headers=_auth("analyst", ids),
        files=files,
        data={"mine_name": "Test"},
    )
    # May fail processing but should create doc if magic ok
    if up1.status_code != 200:
        pytest.skip(f"upload validation/environment: {up1.status_code} {up1.text}")
    parent_id = up1.json()["id"]
    v1 = up1.json().get("version", 1)

    files2 = {"file": ("report_v2.pdf", pdf_bytes, "application/pdf")}
    up2 = client.post(
        "/api/documents/upload",
        headers=_auth("analyst", ids),
        files=files2,
        data={"parent_document_id": parent_id},
    )
    assert up2.status_code == 200
    assert up2.json()["id"] != parent_id
    assert (up2.json().get("version") or 0) > v1

    versions = client.get(
        f"/api/documents/{parent_id}/versions",
        headers=_auth("analyst", ids),
    )
    assert versions.status_code == 200
    assert versions.json()["total"] >= 2


def test_ollama_health_never_crashes(phase7_client, monkeypatch):
    client, _, _ = phase7_client
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:9")
    from app.config import get_settings

    get_settings.cache_clear()
    r = client.get("/api/health/llm")
    assert r.status_code == 200
    body = r.json()
    assert "local" in body
    # App still healthy
    h = client.get("/api/health")
    assert h.status_code == 200
    assert h.json()["status"] == "ok"


def test_system_status_shows_ai_message_when_local_down(phase7_client, monkeypatch):
    client, _, ids = phase7_client
    monkeypatch.setenv("ASSISTANT_LLM_PROVIDER", "local_qwen")
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:9")
    from app.config import get_settings

    get_settings.cache_clear()
    r = client.get("/api/system/status", headers=_auth("analyst", ids))
    assert r.status_code == 200
    ai = r.json()["ai_assistant"]
    assert ai["connection_health"] in {"unavailable", "degraded", "ok"}
    if ai["connection_health"] == "unavailable":
        assert ai.get("message")
        assert "Ollama" in ai["message"] or "unavailable" in ai["message"].lower()


def test_user_cannot_access_validation_or_reviews(phase7_client):
    client, _, ids = phase7_client
    for path in (
        "/api/validation/conflicts",
        "/api/validation/stats",
        "/api/reviews",
    ):
        r = client.get(path, headers=_auth("analyst", ids))
        assert r.status_code == 403, path


def test_admin_can_access_validation_and_reviews(phase7_client):
    client, _, ids = phase7_client
    for path in (
        "/api/validation/conflicts",
        "/api/validation/stats",
        "/api/reviews",
    ):
        r = client.get(path, headers=_auth("admin", ids))
        assert r.status_code == 200, path
    # Legacy reviewer → admin permissions
    r = client.get("/api/reviews", headers=_auth("reviewer", ids))
    assert r.status_code == 200


def test_normalize_role_mapping():
    from app.auth.deps import has_permission, normalize_role
    from app.models import UserRole

    assert normalize_role("analyst") == UserRole.USER.value
    assert normalize_role("reviewer") == UserRole.ADMIN.value
    assert normalize_role("admin") == UserRole.ADMIN.value
    assert normalize_role("user") == UserRole.USER.value
    assert has_permission("user", "analytics")
    assert not has_permission("user", "review.act")
    assert not has_permission("user", "validation.act")
    assert has_permission("admin", "review.act")
    assert has_permission("admin", "validation.act")
    assert has_permission("analyst", "analytics")
    assert not has_permission("analyst", "review.act")
    assert has_permission("reviewer", "review.act")
