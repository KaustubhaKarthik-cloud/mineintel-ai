"""Geological classification + fact extraction (SIH G1)."""

from app.geology.classifier import ClassificationResult, classify_document_text
from app.geology.extractor import GeologicalFactDraft, extract_facts_from_page, extract_facts_from_pages
from app.geology.service import (
    classify_document,
    extract_and_persist_geological_facts,
    geological_fact_to_dict,
    run_geological_pipeline,
)
from app.geology.taxonomy import DOMAIN_LABELS, DocumentDomain

__all__ = [
    "ClassificationResult",
    "DocumentDomain",
    "DOMAIN_LABELS",
    "GeologicalFactDraft",
    "classify_document_text",
    "classify_document",
    "extract_facts_from_page",
    "extract_facts_from_pages",
    "extract_and_persist_geological_facts",
    "geological_fact_to_dict",
    "run_geological_pipeline",
]
