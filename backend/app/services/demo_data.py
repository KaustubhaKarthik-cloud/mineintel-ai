"""Demo / seed data for MineIntel AI prototype (SIH26023).

Frontend and APIs work without live LLM or Postgres.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4


def _days_ago(n: int) -> str:
    return (datetime.utcnow() - timedelta(days=n)).isoformat() + "Z"


DEMO_DOCUMENTS: list[dict[str, Any]] = [
    {
        "id": "doc-001",
        "filename": "bailadila_production_fy24.pdf",
        "original_filename": "Bailadila_Production_Report_FY24.pdf",
        "file_type": "pdf",
        "file_size": 2_450_000,
        "status": "pending_review",
        "mine_name": "Bailadila Iron Ore Mine",
        "document_category": "Production Report",
        "page_count": 24,
        "overall_confidence": 0.78,
        "ocr_completed": True,
        "extraction_completed": True,
        "embedding_completed": True,
        "created_at": _days_ago(2),
    },
    {
        "id": "doc-002",
        "filename": "singareni_safety_audit.xlsx",
        "original_filename": "Singareni_Safety_Audit_Q3.xlsx",
        "file_type": "xlsx",
        "file_size": 890_000,
        "status": "approved",
        "mine_name": "Singareni Collieries",
        "document_category": "Safety Audit",
        "page_count": 12,
        "overall_confidence": 0.94,
        "ocr_completed": True,
        "extraction_completed": True,
        "embedding_completed": True,
        "created_at": _days_ago(5),
    },
    {
        "id": "doc-003",
        "filename": "goa_iron_ore_lease.pdf",
        "original_filename": "Goa_Iron_Ore_Lease_Renewal.pdf",
        "file_type": "pdf",
        "file_size": 3_120_000,
        "status": "processing",
        "mine_name": "Codli Iron Ore Mine",
        "document_category": "Lease Document",
        "page_count": 48,
        "overall_confidence": None,
        "ocr_completed": True,
        "extraction_completed": False,
        "embedding_completed": False,
        "created_at": _days_ago(0),
    },
    {
        "id": "doc-004",
        "filename": "nmdc_environmental_clearance.pdf",
        "original_filename": "NMDC_Environmental_Clearance_2024.pdf",
        "file_type": "pdf",
        "file_size": 5_600_000,
        "status": "extracted",
        "mine_name": "Donimalai Iron Ore Mine",
        "document_category": "Environmental",
        "page_count": 36,
        "overall_confidence": 0.85,
        "ocr_completed": True,
        "extraction_completed": True,
        "embedding_completed": True,
        "created_at": _days_ago(1),
    },
    {
        "id": "doc-005",
        "filename": "odisha_chrome_production.pdf",
        "original_filename": "Odisha_Chrome_Production_H1.pdf",
        "file_type": "pdf",
        "file_size": 1_780_000,
        "status": "pending_review",
        "mine_name": "Sukinda Chromite Mine",
        "document_category": "Production Report",
        "page_count": 18,
        "overall_confidence": 0.62,
        "ocr_completed": True,
        "extraction_completed": True,
        "embedding_completed": True,
        "created_at": _days_ago(3),
    },
    {
        "id": "doc-006",
        "filename": "hindustan_zinc_ore_grade.xlsx",
        "original_filename": "HZL_Ore_Grade_Analysis.xlsx",
        "file_type": "xlsx",
        "file_size": 420_000,
        "status": "approved",
        "mine_name": "Rampura Agucha Mine",
        "document_category": "Grade Analysis",
        "page_count": 8,
        "overall_confidence": 0.91,
        "ocr_completed": True,
        "extraction_completed": True,
        "embedding_completed": True,
        "created_at": _days_ago(8),
    },
    {
        "id": "doc-007",
        "filename": "coal_india_monthly_scan.jpg",
        "original_filename": "CIL_Monthly_Returns_Scan.jpg",
        "file_type": "image",
        "file_size": 3_900_000,
        "status": "failed",
        "mine_name": "Jharia Coalfields",
        "document_category": "Monthly Return",
        "page_count": 1,
        "overall_confidence": 0.31,
        "ocr_completed": False,
        "extraction_completed": False,
        "embedding_completed": False,
        "created_at": _days_ago(4),
    },
    {
        "id": "doc-008",
        "filename": "vedanta_bauxite_report.pdf",
        "original_filename": "Vedanta_Bauxite_Ops_Report.pdf",
        "file_type": "pdf",
        "file_size": 2_100_000,
        "status": "approved",
        "mine_name": "Lanjigarh Bauxite",
        "document_category": "Operations Report",
        "page_count": 22,
        "overall_confidence": 0.88,
        "ocr_completed": True,
        "extraction_completed": True,
        "embedding_completed": True,
        "created_at": _days_ago(10),
    },
]

DEMO_REVIEWS: list[dict[str, Any]] = [
    {
        "id": "rev-001",
        "document_id": "doc-001",
        "document_name": "Bailadila_Production_Report_FY24.pdf",
        "field_name": "annual_production_mt",
        "extracted_value": "18.4",
        "corrected_value": None,
        "confidence": 0.71,
        "status": "pending",
        "priority": 3,
        "mine_name": "Bailadila Iron Ore Mine",
        "created_at": _days_ago(2),
    },
    {
        "id": "rev-002",
        "document_id": "doc-001",
        "document_name": "Bailadila_Production_Report_FY24.pdf",
        "field_name": "lease_area_ha",
        "extracted_value": "1847.5",
        "corrected_value": None,
        "confidence": 0.68,
        "status": "pending",
        "priority": 2,
        "mine_name": "Bailadila Iron Ore Mine",
        "created_at": _days_ago(2),
    },
    {
        "id": "rev-003",
        "document_id": "doc-005",
        "document_name": "Odisha_Chrome_Production_H1.pdf",
        "field_name": "chrome_ore_grade_pct",
        "extracted_value": "42.8",
        "corrected_value": None,
        "confidence": 0.55,
        "status": "pending",
        "priority": 3,
        "mine_name": "Sukinda Chromite Mine",
        "created_at": _days_ago(3),
    },
    {
        "id": "rev-004",
        "document_id": "doc-005",
        "document_name": "Odisha_Chrome_Production_H1.pdf",
        "field_name": "safety_incidents",
        "extracted_value": "2",
        "corrected_value": None,
        "confidence": 0.74,
        "status": "pending",
        "priority": 2,
        "mine_name": "Sukinda Chromite Mine",
        "created_at": _days_ago(3),
    },
    {
        "id": "rev-005",
        "document_id": "doc-004",
        "document_name": "NMDC_Environmental_Clearance_2024.pdf",
        "field_name": "afforestation_ha",
        "extracted_value": "125.0",
        "corrected_value": None,
        "confidence": 0.79,
        "status": "pending",
        "priority": 1,
        "mine_name": "Donimalai Iron Ore Mine",
        "created_at": _days_ago(1),
    },
    {
        "id": "rev-006",
        "document_id": "doc-002",
        "document_name": "Singareni_Safety_Audit_Q3.xlsx",
        "field_name": "fatal_incidents",
        "extracted_value": "0",
        "corrected_value": "0",
        "confidence": 0.96,
        "status": "approved",
        "priority": 3,
        "mine_name": "Singareni Collieries",
        "created_at": _days_ago(5),
    },
]

DEMO_CHAT_RESPONSES: dict[str, dict[str, Any]] = {
    "default": {
        "reply": (
            "Based on validated mining records in MineIntel, Bailadila Iron Ore Mine "
            "reported approximately 18.4 MT annual production (pending review), while "
            "Rampura Agucha and Lanjigarh show approved operational data. "
            "I can break this down by mineral, state, or reporting period."
        ),
        "sources": [
            {
                "document_id": "doc-001",
                "document_name": "Bailadila_Production_Report_FY24.pdf",
                "snippet": "Total iron ore production for FY 2023-24 stood at 18.4 million tonnes...",
                "relevance": 0.92,
            },
            {
                "document_id": "doc-006",
                "document_name": "HZL_Ore_Grade_Analysis.xlsx",
                "snippet": "Average zinc grade at Rampura Agucha: 12.4% Zn...",
                "relevance": 0.81,
            },
        ],
    },
    "production": {
        "reply": (
            "Production overview (demo intelligence layer):\n\n"
            "• Iron ore — Bailadila ~18.4 MT (under review), Donimalai clearance linked\n"
            "• Chromite — Sukinda H1 figures pending low-confidence grade validation\n"
            "• Coal — Singareni safety audit approved; Jharia OCR failed and needs re-upload\n"
            "• Bauxite — Lanjigarh ops report approved\n\n"
            "Recommend prioritizing review items with confidence < 0.75 before analytics export."
        ),
        "sources": [
            {
                "document_id": "doc-001",
                "document_name": "Bailadila_Production_Report_FY24.pdf",
                "snippet": "Annual production tabulated by pit and beneficiation plant...",
                "relevance": 0.94,
            },
            {
                "document_id": "doc-005",
                "document_name": "Odisha_Chrome_Production_H1.pdf",
                "snippet": "Chrome ore grade reported inconsistently across annexures...",
                "relevance": 0.87,
            },
        ],
    },
    "safety": {
        "reply": (
            "Safety intelligence (demo):\n\n"
            "Singareni Collieries Q3 audit shows zero fatal incidents (approved, 96% confidence). "
            "Sukinda has 2 reported incidents awaiting human verification. "
            "No validated safety metrics yet for Bailadila in the current batch."
        ),
        "sources": [
            {
                "document_id": "doc-002",
                "document_name": "Singareni_Safety_Audit_Q3.xlsx",
                "snippet": "Fatalities: 0 | Lost-time injuries: 3 | Near misses: 14",
                "relevance": 0.95,
            },
        ],
    },
}


def get_dashboard_stats() -> dict[str, Any]:
    docs = DEMO_DOCUMENTS
    pending = sum(1 for d in docs if d["status"] == "pending_review")
    approved = sum(1 for d in docs if d["status"] == "approved")
    processing = sum(1 for d in docs if d["status"] in ("processing", "uploaded", "extracted"))
    confidences = [d["overall_confidence"] for d in docs if d["overall_confidence"] is not None]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

    return {
        "total_documents": len(docs),
        "pending_review": pending,
        "approved_records": approved,
        "avg_confidence": round(avg_conf, 2),
        "processing_queue": processing,
        "topics_tracked": 6,
        "reports_generated": 4,
        "recent_documents": sorted(docs, key=lambda d: d["created_at"], reverse=True)[:5],
        "recent_activity": [
            {
                "id": "act-1",
                "action": "Document uploaded",
                "detail": "Goa_Iron_Ore_Lease_Renewal.pdf",
                "actor": "ops.analyst",
                "timestamp": _days_ago(0),
            },
            {
                "id": "act-2",
                "action": "Extraction completed",
                "detail": "NMDC_Environmental_Clearance_2024.pdf — 14 fields",
                "actor": "system",
                "timestamp": _days_ago(1),
            },
            {
                "id": "act-3",
                "action": "Review approved",
                "detail": "Singareni fatal_incidents = 0",
                "actor": "reviewer.mehta",
                "timestamp": _days_ago(5),
            },
            {
                "id": "act-4",
                "action": "OCR failed",
                "detail": "CIL_Monthly_Returns_Scan.jpg — low image quality",
                "actor": "system",
                "timestamp": _days_ago(4),
            },
        ],
        "pipeline_status": {
            "ingestion": "operational",
            "ocr_parsing": "operational",
            "ai_extraction": "demo",
            "human_review": "operational",
            "rag_embeddings": "demo",
            "intelligence": "demo",
        },
    }


def get_analytics() -> dict[str, Any]:
    return {
        "kpis": [
            {"label": "Total Production (validated)", "value": "42.6", "change": 4.2, "unit": "MT"},
            {"label": "Documents Processed", "value": 8, "change": 12.5, "unit": None},
            {"label": "Avg Extraction Confidence", "value": 0.76, "change": -3.1, "unit": None},
            {"label": "Review Backlog", "value": 5, "change": -8.0, "unit": None},
        ],
        "production_by_mineral": [
            {"mineral": "Iron Ore", "production": 28.4},
            {"mineral": "Coal", "production": 6.2},
            {"mineral": "Bauxite", "production": 4.1},
            {"mineral": "Chromite", "production": 2.8},
            {"mineral": "Zinc", "production": 1.1},
        ],
        "documents_by_status": [
            {"status": "Approved", "count": 3},
            {"status": "Pending Review", "count": 2},
            {"status": "Processing", "count": 1},
            {"status": "Extracted", "count": 1},
            {"status": "Failed", "count": 1},
        ],
        "monthly_uploads": [
            {"month": "Apr", "uploads": 4},
            {"month": "May", "uploads": 7},
            {"month": "Jun", "uploads": 5},
            {"month": "Jul", "uploads": 9},
            {"month": "Aug", "uploads": 11},
            {"month": "Sep", "uploads": 8},
        ],
        "confidence_distribution": [
            {"bucket": "0–40%", "count": 1},
            {"bucket": "40–60%", "count": 1},
            {"bucket": "60–80%", "count": 3},
            {"bucket": "80–100%", "count": 3},
        ],
        "top_mines": [
            {"mine": "Bailadila", "documents": 12, "production": 18.4},
            {"mine": "Singareni", "documents": 9, "production": 6.2},
            {"mine": "Donimalai", "documents": 7, "production": 5.8},
            {"mine": "Sukinda", "documents": 6, "production": 2.8},
            {"mine": "Lanjigarh", "documents": 5, "production": 4.1},
        ],
    }


def chat_reply(message: str, session_id: str | None = None) -> dict[str, Any]:
    sid = session_id or str(uuid4())
    lower = message.lower()
    if any(k in lower for k in ("safety", "incident", "fatal")):
        payload = DEMO_CHAT_RESPONSES["safety"]
    elif any(k in lower for k in ("production", "output", "tonnage", "mt")):
        payload = DEMO_CHAT_RESPONSES["production"]
    else:
        payload = DEMO_CHAT_RESPONSES["default"]
    return {"session_id": sid, "reply": payload["reply"], "sources": payload["sources"]}


DEMO_TOPICS = [
    {"id": "t1", "name": "Iron Ore Production", "document_count": 3, "keywords": ["iron", "bailadila", "nmdc"]},
    {"id": "t2", "name": "Mine Safety", "document_count": 2, "keywords": ["safety", "incident", "audit"]},
    {"id": "t3", "name": "Environmental Clearance", "document_count": 2, "keywords": ["environment", "afforestation"]},
    {"id": "t4", "name": "Lease & Compliance", "document_count": 1, "keywords": ["lease", "renewal", "goa"]},
    {"id": "t5", "name": "Ore Grade Analysis", "document_count": 2, "keywords": ["grade", "zinc", "chrome"]},
    {"id": "t6", "name": "Coal Operations", "document_count": 2, "keywords": ["coal", "singareni", "jharia"]},
]

DEMO_REPORTS = [
    {
        "id": "rpt-1",
        "title": "Q2 Mining Production Summary",
        "report_type": "summary",
        "status": "ready",
        "generated_by": "system",
        "created_at": _days_ago(3),
    },
    {
        "id": "rpt-2",
        "title": "Safety Compliance Digest",
        "report_type": "safety",
        "status": "ready",
        "generated_by": "reviewer.mehta",
        "created_at": _days_ago(6),
    },
    {
        "id": "rpt-3",
        "title": "Low-Confidence Extraction Report",
        "report_type": "quality",
        "status": "draft",
        "generated_by": "system",
        "created_at": _days_ago(1),
    },
    {
        "id": "rpt-4",
        "title": "State-wise Mineral Intelligence",
        "report_type": "analytics",
        "status": "ready",
        "generated_by": "ops.analyst",
        "created_at": _days_ago(9),
    },
]

DEMO_AUDIT_LOGS = [
    {
        "id": "aud-1",
        "action": "UPLOAD",
        "entity_type": "document",
        "entity_id": "doc-003",
        "actor": "ops.analyst",
        "details": {"filename": "Goa_Iron_Ore_Lease_Renewal.pdf"},
        "created_at": _days_ago(0),
    },
    {
        "id": "aud-2",
        "action": "EXTRACT",
        "entity_type": "document",
        "entity_id": "doc-004",
        "actor": "system",
        "details": {"fields": 14},
        "created_at": _days_ago(1),
    },
    {
        "id": "aud-3",
        "action": "REVIEW_APPROVE",
        "entity_type": "review_item",
        "entity_id": "rev-006",
        "actor": "reviewer.mehta",
        "details": {"field": "fatal_incidents"},
        "created_at": _days_ago(5),
    },
    {
        "id": "aud-4",
        "action": "OCR_FAIL",
        "entity_type": "document",
        "entity_id": "doc-007",
        "actor": "system",
        "details": {"reason": "low_image_quality"},
        "created_at": _days_ago(4),
    },
]
