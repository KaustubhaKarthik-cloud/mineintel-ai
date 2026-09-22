"""Regression: geological review_required facts appear in the shared Review Queue."""

from __future__ import annotations

from app.models import Document, FactStatus, GeologicalFact, IndexStatus, ReviewItem, ReviewStatus


def _doc(db, name: str = "geo_review_doc.pdf") -> Document:
    d = Document(
        filename=name,
        original_filename=name,
        file_path=f"/tmp/{name}",
        file_type="pdf",
        status="extracted",
        index_status=IndexStatus.INDEXED.value,
        document_category="Geological Exploration Report",
        version=1,
        meta={
            "g1_classification": {
                "domain": "geological_exploration",
                "label": "Geological Exploration Report",
                "confidence": 0.9,
            }
        },
    )
    db.add(d)
    db.flush()
    return d


def _geo_fact(db, doc: Document, **kwargs) -> GeologicalFact:
    defaults = {
        "document_id": doc.id,
        "domain": "geological",
        "metric_kind": "resource_quantity",
        "status": FactStatus.REVIEW_REQUIRED.value,
        "extraction_confidence": 0.62,
        "source_page": 17,
        "original_value": "2.45",
        "original_unit": "MT",
        "original_extracted_value": "2.45",
        "evidence_text": "Resource estimate of 2.45 MT is stated in the table.",
        "seam_name": "Seam Alpha",
    }
    defaults.update(kwargs)
    row = GeologicalFact(**defaults)
    db.add(row)
    db.flush()
    return row


def test_review_required_geological_fact_appears_in_review_queue(client, db_session, admin_headers):
    doc = _doc(db_session, "pending_geo.pdf")
    fact = _geo_fact(db_session, doc)
    db_session.commit()

    # Before fix: GET /reviews ignored GeologicalFact.review_required entirely.
    resp = client.get("/api/reviews", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pending"] >= 1
    match = next((i for i in body["items"] if i.get("geological_fact_id") == fact.id), None)
    assert match is not None, "review_required geological fact must appear in Review Queue"

    # Provenance for human verification
    assert match["status"] == ReviewStatus.PENDING.value
    assert match["document_id"] == doc.id
    assert match["extracted_value"] == "2.45"
    assert match["original_unit"] == "MT"
    assert match["page_number"] == 17
    assert match["geological_fact_id"] == fact.id
    assert match["source_document"] == doc.original_filename
    assert match["evidence_text"]
    assert "geological" in (match["field_name"] or "")


def test_rejected_and_verified_geological_facts_not_in_review_queue(client, db_session, admin_headers):
    doc = _doc(db_session, "resolved_geo.pdf")
    pending = _geo_fact(
        db_session,
        doc,
        original_value="3.1",
        original_extracted_value="3.1",
        evidence_text="Pending resource figure of 3.1 MT.",
        source_page=4,
    )
    rejected = _geo_fact(
        db_session,
        doc,
        status=FactStatus.REJECTED.value,
        original_value="9.9",
        original_extracted_value="9.9",
        evidence_text="Rejected spurious figure.",
        source_page=5,
        seam_name="Seam Beta",
    )
    verified = _geo_fact(
        db_session,
        doc,
        status=FactStatus.APPROVED.value,
        original_value="1.2",
        original_extracted_value="1.2",
        evidence_text="Verified thickness already approved.",
        source_page=6,
        metric_kind="seam_thickness",
        seam_name="Seam Gamma",
    )
    # Stale pending ReviewItem pointing at rejected/verified must not stay in queue
    db_session.add(
        ReviewItem(
            document_id=doc.id,
            geological_fact_id=rejected.id,
            field_name="geological.resource_quantity",
            extracted_value="9.9",
            status=ReviewStatus.PENDING.value,
            confidence=0.4,
        )
    )
    db_session.add(
        ReviewItem(
            document_id=doc.id,
            geological_fact_id=verified.id,
            field_name="geological.seam_thickness",
            extracted_value="1.2",
            status=ReviewStatus.PENDING.value,
            confidence=0.9,
        )
    )
    db_session.commit()

    body = client.get("/api/reviews", headers=admin_headers).json()
    ids = {i.get("geological_fact_id") for i in body["items"]}
    assert pending.id in ids
    assert rejected.id not in ids
    assert verified.id not in ids
    assert all(i["status"] == ReviewStatus.PENDING.value for i in body["items"])


def test_queue_action_rejects_geological_fact_and_removes_from_queue(client, db_session, admin_headers):
    doc = _doc(db_session, "action_geo.pdf")
    fact = _geo_fact(
        db_session,
        doc,
        original_value="0.88",
        original_extracted_value="0.88",
        evidence_text="Provisional quantity 0.88 MT needs review.",
    )
    db_session.commit()

    queue = client.get("/api/reviews", headers=admin_headers).json()
    item = next(i for i in queue["items"] if i["geological_fact_id"] == fact.id)

    rej = client.post(
        f"/api/reviews/{item['id']}/action",
        headers=admin_headers,
        json={"action": "reject", "review_notes": "Not supported by table", "reviewer": "geo_reviewer"},
    )
    assert rej.status_code == 200, rej.text
    assert rej.json()["status"] == ReviewStatus.REJECTED.value

    after = client.get("/api/reviews", headers=admin_headers).json()
    assert fact.id not in {i.get("geological_fact_id") for i in after["items"]}

    db_session.refresh(fact)
    assert fact.status == FactStatus.REJECTED.value
