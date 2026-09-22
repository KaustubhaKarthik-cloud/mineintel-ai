"""Pytest fixtures for MineIntel Phase 2 tests."""

from __future__ import annotations

import io
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure app imports use test settings where needed
from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    """Isolated in-memory SQLite for each test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    # Redirect document storage into tmp
    docs = tmp_path / "documents"
    (docs / "original").mkdir(parents=True)
    (docs / "processed").mkdir(parents=True)

    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("DEMO_MODE", "true")
    # Tests use anonymous least-privilege USER (no review/validation). Production defaults AUTH_REQUIRED=true.
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    # Keep unit tests on Tesseract so the suite does not load heavy Paddle models.
    monkeypatch.setenv("OCR_ENGINE", "tesseract")
    monkeypatch.setenv("OCR_FALLBACK", "tesseract")

    from app.utils import files as files_mod
    from app import config as config_mod

    monkeypatch.setattr(files_mod, "documents_root", lambda: docs)
    config_mod.get_settings.cache_clear()

    session = TestingSession()

    def _override():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    try:
        yield session
    finally:
        session.close()
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=engine)
        config_mod.get_settings.cache_clear()


@pytest.fixture()
def client(db_session):
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin_user(db_session):
    """Seed an ADMIN for tests that exercise review/validation/admin APIs."""
    from app.auth.security import hash_password
    from app.models import User, UserRole, UserStatus

    existing = db_session.query(User).filter(User.username == "admin").first()
    if existing:
        existing.role = UserRole.ADMIN.value
        existing.status = UserStatus.ACTIVE.value
        db_session.commit()
        return existing
    user = User(
        username="admin",
        display_name="Test Admin",
        password_hash=hash_password("admin123"),
        role=UserRole.ADMIN.value,
        status=UserStatus.ACTIVE.value,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def admin_headers(admin_user):
    """Auth as ADMIN via X-Demo-User when AUTH_REQUIRED=false (anonymous is USER-only)."""
    return {"X-Demo-User": admin_user.username}


@pytest.fixture()
def user_headers(db_session):
    """Auth as least-privilege USER."""
    from app.auth.security import hash_password
    from app.models import User, UserRole, UserStatus

    existing = db_session.query(User).filter(User.username == "user").first()
    if not existing:
        existing = User(
            username="user",
            display_name="Test User",
            password_hash=hash_password("user123"),
            role=UserRole.USER.value,
            status=UserStatus.ACTIVE.value,
        )
        db_session.add(existing)
        db_session.commit()
        db_session.refresh(existing)
    return {"X-Demo-User": existing.username}


@pytest.fixture()
def fixtures_dir(tmp_path) -> Path:
    root = tmp_path / "fixtures"
    root.mkdir()
    return root


@pytest.fixture()
def digital_pdf(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "Annual_Report_2024.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text(
        (72, 72),
        "MineIntel Annual Report FY2024\n\n"
        "Bailadila Iron Ore Mine overview and production summary.",
        fontsize=12,
    )
    page2 = doc.new_page()
    page2.insert_text(
        (72, 72),
        "Page 2 — Operations\n\n"
        "Mine B produced 3.9 MT during FY2024 against a target of 5.0 MT.",
        fontsize=12,
    )
    # Extra pages so page 42 citation story works in a short demo PDF as page 3 labeled
    page3 = doc.new_page()
    page3.insert_text(
        (72, 72),
        "Annexure — Detailed Production\n\n"
        "Mine B produced 3.9 MT during FY2024. Lease area 1847.5 ha.",
        fontsize=12,
    )
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def scanned_pdf(fixtures_dir: Path) -> Path:
    """PDF with an image page and no selectable text (requires OCR)."""
    path = fixtures_dir / "Scanned_Inspection.pdf"
    # Create an image with text, embed in PDF without text layer
    img = Image.new("RGB", (800, 400), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((40, 160), "Scanned Inspection: Mine B safety checklist OK", fill=(0, 0, 0))
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)

    doc = fitz.open()
    page = doc.new_page(width=800, height=400)
    page.insert_image(page.rect, stream=img_bytes.getvalue())
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def production_xlsx(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "Production.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "FY2024"
    ws.append(["Mine", "Production", "Target"])
    ws.append(["Mine A", "4.8", "5.0"])
    ws.append(["Mine B", "3.9", "5.0"])
    wb.save(path)
    return path


@pytest.fixture()
def sample_png(fixtures_dir: Path) -> Path:
    path = fixtures_dir / "inspection.png"
    img = Image.new("RGB", (640, 200), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((20, 80), "Mine B produced 3.9 MT in FY2024", fill=(0, 0, 0))
    img.save(path)
    return path
