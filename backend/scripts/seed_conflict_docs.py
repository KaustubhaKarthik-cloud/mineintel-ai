"""Seed demo documents with deliberate Mine B FY2024 contradictions."""

from __future__ import annotations

import sys
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.database import SessionLocal, init_db
from app.main import app
from app.models import Document, ExtractedFact, FactStatus

init_db()
docs_dir = Path(__file__).resolve().parents[1] / "documents" / "demo"
docs_dir.mkdir(parents=True, exist_ok=True)

specs = [
    (
        "Annual_Report_2024_MineB.pdf",
        [
            "Annual Report 2024 — Mine B Operations",
            "Mine B produced 5.2 MT during FY2024 against a target of 5.0 MT.",
            "Reported achievement for Mine B FY2024 was 82 percent.",
            "Lease area at Mine B remains 1847.5 ha.",
        ],
    ),
    (
        "Production_Report_2024_MineB.pdf",
        [
            "Production Report FY2024 — Mine B",
            "Production from Mine B was 5.6 MT in FY2024.",
            "Mine B production target for FY2024 was 5.0 MT.",
            "Dispatch from Mine B FY2024 totaled 5.1 MT.",
        ],
    ),
    (
        "Ops_Summary_2024_MineB.pdf",
        [
            "Operations Summary FY2024",
            "Mine B annual production was 5.2 MT for FY2024.",
        ],
    ),
]

paths: list[Path] = []
for name, lines in specs:
    path = docs_dir / name
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for i, line in enumerate(lines):
        page.insert_text((72, y), line, fontsize=14 if i == 0 else 11)
        y += 30 if i == 0 else 28
    doc.save(path)
    doc.close()
    paths.append(path)
    print("created", path)

client = TestClient(app)
uploaded = []
for path in paths:
    with path.open("rb") as f:
        r = client.post(
            "/api/documents/upload",
            files={"file": (path.name, f, "application/pdf")},
            data={"mine_name": "Mine B", "document_category": "Production Report"},
        )
    print("upload", path.name, r.status_code, r.json().get("status"), r.json().get("id"))
    uploaded.append(r.json())

for u in uploaded:
    r = client.post(f"/api/documents/{u['id']}/extract")
    print("extract", u["original_filename"], r.status_code, "facts", len(r.json().get("facts", [])))


def ensure(
    db,
    docs: dict[str, Document],
    doc_name: str,
    field: str,
    value: float,
    unit: str,
    page: int,
    evidence: str,
    fy: str = "FY2024",
) -> None:
    d = docs[doc_name]
    existing = (
        db.query(ExtractedFact)
        .filter(
            ExtractedFact.document_id == d.id,
            ExtractedFact.field_name == field,
            ExtractedFact.entity_name == "Mine B",
            ExtractedFact.financial_year == fy,
        )
        .first()
    )
    if existing:
        existing.value = str(value)
        existing.numeric_value = float(value)
        existing.unit = unit
        existing.evidence_text = evidence
        existing.page_number = page
        existing.status = FactStatus.HIGH_CONFIDENCE.value
        existing.confidence_score = 0.95
    else:
        db.add(
            ExtractedFact(
                document_id=d.id,
                field_name=field,
                value=str(value),
                numeric_value=float(value),
                unit=unit,
                entity_name="Mine B",
                financial_year=fy,
                page_number=page,
                evidence_text=evidence,
                confidence_score=0.95,
                status=FactStatus.HIGH_CONFIDENCE.value,
            )
        )


db = SessionLocal()
try:
    names = [p.name for p in paths]
    docs = {
        d.original_filename: d
        for d in db.query(Document).filter(Document.original_filename.in_(names)).all()
    }
    ensure(
        db,
        docs,
        "Annual_Report_2024_MineB.pdf",
        "production",
        5.2,
        "MT",
        1,
        "Mine B produced 5.2 MT during FY2024 against a target of 5.0 MT.",
    )
    ensure(
        db,
        docs,
        "Annual_Report_2024_MineB.pdf",
        "production_target",
        5.0,
        "MT",
        1,
        "against a target of 5.0 MT",
    )
    ensure(
        db,
        docs,
        "Annual_Report_2024_MineB.pdf",
        "achievement_percentage",
        82,
        "%",
        1,
        "Reported achievement for Mine B FY2024 was 82 percent.",
    )
    ensure(
        db,
        docs,
        "Production_Report_2024_MineB.pdf",
        "production",
        5.6,
        "MT",
        1,
        "Production from Mine B was 5.6 MT in FY2024.",
    )
    ensure(
        db,
        docs,
        "Production_Report_2024_MineB.pdf",
        "production_target",
        5.0,
        "MT",
        1,
        "Mine B production target for FY2024 was 5.0 MT.",
    )
    ensure(
        db,
        docs,
        "Ops_Summary_2024_MineB.pdf",
        "production",
        5.2,
        "MT",
        1,
        "Mine B annual production was 5.2 MT for FY2024.",
    )
    db.commit()
finally:
    db.close()

r = client.post("/api/validation/run")
print("validation", r.status_code, r.json())
conflicts = client.get("/api/validation/conflicts").json()
print("conflicts", conflicts["total"])
for c in conflicts["items"]:
    print("-", c["conflict_type"], c["field_name"], c["entity_name"], c["period"], c["status"])
    for e in c["evidence"]:
        print(
            " ",
            e.get("label"),
            e.get("document_name"),
            f"p{e.get('page_number')}",
            e.get("value"),
            e.get("unit"),
        )

for u in uploaded:
    ir = client.post(f"/api/documents/{u['id']}/index")
    body = ir.json()
    print(
        "index",
        u["original_filename"],
        ir.status_code,
        body.get("index_status"),
        body.get("chunk_count"),
    )

print("DONE")
