"""Database engine and session management.

Supports SQLite for local demo and PostgreSQL (+ pgvector later) via DATABASE_URL.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

settings = get_settings()

connect_args = {}
if settings.use_sqlite:
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.effective_database_url,
    connect_args=connect_args,
    echo=settings.debug and not settings.use_sqlite,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _sqlite_add_missing_columns() -> None:
    """Lightweight migrate for Phase 2/3 columns when reusing an older SQLite file."""
    if not settings.use_sqlite:
        return
    insp = inspect(engine)
    tables = insp.get_table_names()
    if "documents" not in tables:
        return
    existing = {c["name"] for c in insp.get_columns("documents")}
    alters = [
        ("processing_stage", "ALTER TABLE documents ADD COLUMN processing_stage VARCHAR(64)"),
        ("processing_started_at", "ALTER TABLE documents ADD COLUMN processing_started_at DATETIME"),
        ("processing_completed_at", "ALTER TABLE documents ADD COLUMN processing_completed_at DATETIME"),
        ("version", "ALTER TABLE documents ADD COLUMN version INTEGER DEFAULT 1 NOT NULL"),
        ("is_scanned", "ALTER TABLE documents ADD COLUMN is_scanned BOOLEAN DEFAULT 0 NOT NULL"),
        ("index_status", "ALTER TABLE documents ADD COLUMN index_status VARCHAR(32) DEFAULT 'not_indexed'"),
        ("indexed_at", "ALTER TABLE documents ADD COLUMN indexed_at DATETIME"),
        ("index_error", "ALTER TABLE documents ADD COLUMN index_error TEXT"),
    ]
    with engine.begin() as conn:
        for col, sql in alters:
            if col not in existing:
                conn.execute(text(sql))

    if "review_items" in tables:
        rev_cols = {c["name"] for c in insp.get_columns("review_items")}
        rev_alters = [
            ("extracted_fact_id", "ALTER TABLE review_items ADD COLUMN extracted_fact_id VARCHAR(36)"),
            ("original_unit", "ALTER TABLE review_items ADD COLUMN original_unit VARCHAR(64)"),
            ("corrected_unit", "ALTER TABLE review_items ADD COLUMN corrected_unit VARCHAR(64)"),
            ("entity_name", "ALTER TABLE review_items ADD COLUMN entity_name VARCHAR(256)"),
            ("financial_year", "ALTER TABLE review_items ADD COLUMN financial_year VARCHAR(64)"),
            ("evidence_text", "ALTER TABLE review_items ADD COLUMN evidence_text TEXT"),
            ("page_number", "ALTER TABLE review_items ADD COLUMN page_number INTEGER"),
            ("sheet_name", "ALTER TABLE review_items ADD COLUMN sheet_name VARCHAR(256)"),
            ("source_document", "ALTER TABLE review_items ADD COLUMN source_document VARCHAR(512)"),
        ]
        with engine.begin() as conn:
            for col, sql in rev_alters:
                if col not in rev_cols:
                    conn.execute(text(sql))

    if "document_chunks" in tables:
        chunk_cols = {c["name"] for c in insp.get_columns("document_chunks")}
        chunk_alters = [
            ("document_page_id", "ALTER TABLE document_chunks ADD COLUMN document_page_id VARCHAR(36)"),
            ("content_type", "ALTER TABLE document_chunks ADD COLUMN content_type VARCHAR(64) DEFAULT 'document_evidence'"),
            ("sheet_name", "ALTER TABLE document_chunks ADD COLUMN sheet_name VARCHAR(256)"),
            ("source_type", "ALTER TABLE document_chunks ADD COLUMN source_type VARCHAR(32)"),
            ("source_location", "ALTER TABLE document_chunks ADD COLUMN source_location VARCHAR(512)"),
            ("document_name", "ALTER TABLE document_chunks ADD COLUMN document_name VARCHAR(512)"),
            ("document_version", "ALTER TABLE document_chunks ADD COLUMN document_version INTEGER DEFAULT 1"),
            ("is_active", "ALTER TABLE document_chunks ADD COLUMN is_active BOOLEAN DEFAULT 1"),
            ("updated_at", "ALTER TABLE document_chunks ADD COLUMN updated_at DATETIME"),
        ]
        with engine.begin() as conn:
            for col, sql in chunk_alters:
                if col not in chunk_cols:
                    conn.execute(text(sql))

    if "topics" in tables:
        topic_cols = {c["name"] for c in insp.get_columns("topics")}
        topic_alters = [
            ("slug", "ALTER TABLE topics ADD COLUMN slug VARCHAR(256)"),
            ("chunk_count", "ALTER TABLE topics ADD COLUMN chunk_count INTEGER DEFAULT 0"),
            ("confidence", "ALTER TABLE topics ADD COLUMN confidence FLOAT"),
            ("summary", "ALTER TABLE topics ADD COLUMN summary TEXT"),
            ("summary_citations", "ALTER TABLE topics ADD COLUMN summary_citations JSON"),
            ("last_extracted_at", "ALTER TABLE topics ADD COLUMN last_extracted_at DATETIME"),
            ("updated_at", "ALTER TABLE topics ADD COLUMN updated_at DATETIME"),
        ]
        with engine.begin() as conn:
            for col, sql in topic_alters:
                if col not in topic_cols:
                    conn.execute(text(sql))

    # Phase 7 — document versioning columns
    if "documents" in tables:
        existing = {c["name"] for c in insp.get_columns("documents")}
        doc_alters = [
            ("parent_document_id", "ALTER TABLE documents ADD COLUMN parent_document_id VARCHAR(36)"),
            ("replaces_document_id", "ALTER TABLE documents ADD COLUMN replaces_document_id VARCHAR(36)"),
        ]
        with engine.begin() as conn:
            for col, sql in doc_alters:
                if col not in existing:
                    conn.execute(text(sql))

    # Phase 7 — report metadata columns
    if "reports" in tables:
        report_cols = {c["name"] for c in insp.get_columns("reports")}
        report_alters = [
            ("created_by_user_id", "ALTER TABLE reports ADD COLUMN created_by_user_id VARCHAR(36)"),
            ("source_document_ids", "ALTER TABLE reports ADD COLUMN source_document_ids JSON"),
            ("selected_entities", "ALTER TABLE reports ADD COLUMN selected_entities JSON"),
            ("selected_periods", "ALTER TABLE reports ADD COLUMN selected_periods JSON"),
            ("output_path", "ALTER TABLE reports ADD COLUMN output_path VARCHAR(1024)"),
            ("output_format", "ALTER TABLE reports ADD COLUMN output_format VARCHAR(32) DEFAULT 'html'"),
            ("provenance", "ALTER TABLE reports ADD COLUMN provenance JSON"),
            ("updated_at", "ALTER TABLE reports ADD COLUMN updated_at DATETIME"),
        ]
        with engine.begin() as conn:
            for col, sql in report_alters:
                if col not in report_cols:
                    conn.execute(text(sql))


def init_db() -> None:
    """Create tables and apply lightweight SQLite migrations. Safe on startup."""
    from app import models  # noqa: F401
    from app.auth.seed import seed_default_users
    from app.config import get_settings

    Base.metadata.create_all(bind=engine)
    _sqlite_add_missing_columns()

    settings = get_settings()
    if settings.auth_seed_users:
        db = SessionLocal()
        try:
            created = seed_default_users(db)
            if created:
                print(f"[MineIntel] Seeded {created} default user(s)")
        except Exception as exc:  # noqa: BLE001
            print(f"[MineIntel] User seed skipped: {exc}")
        finally:
            db.close()


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
    if settings.use_sqlite:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
