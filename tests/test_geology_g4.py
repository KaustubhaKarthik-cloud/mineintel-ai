"""G4 — Geological Explorer + Analytics regression tests."""

from __future__ import annotations

from app.geology import explorer as geo_explorer
from app.geology import geo_analytics
from app.geology.metric_kinds import (
    BOREHOLE_DEPTH,
    MINIMUM_WORKABLE_SEAM_THICKNESS,
    RESOURCE_QUANTITY,
    SEAM_THICKNESS,
)
from app.models import Document, FactStatus, GeologicalFact, IndexStatus


def _doc(db, name="g4_report.pdf") -> Document:
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


def _fact(db, doc: Document, **kwargs) -> GeologicalFact:
    defaults = {
        "document_id": doc.id,
        "domain": "geological",
        "status": FactStatus.REVIEW_REQUIRED.value,
        "extraction_confidence": 0.7,
        "source_page": 10,
        "evidence_text": "structured geological evidence",
    }
    defaults.update(kwargs)
    row = GeologicalFact(**defaults)
    db.add(row)
    db.flush()
    return row


def _seed_basic(db):
    doc = _doc(db, "alpha_geo.pdf")
    _fact(
        db,
        doc,
        metric_kind="formation",
        geological_formation="Raniganj Formation",
        source_page=11,
        evidence_text="The Raniganj Formation hosts coal seams.",
        original_value="Raniganj Formation",
    )
    _fact(
        db,
        doc,
        metric_kind="formation",
        geological_formation="Barakar Formation",
        source_page=33,
        evidence_text="Barakar Formation is present in the block.",
        original_value="Barakar Formation",
    )
    _fact(
        db,
        doc,
        metric_kind="seam",
        seam_name="R4",
        seam_status="named",
        geological_formation="Raniganj Formation",
        source_page=12,
        evidence_text="Seam R4 occurs in the Raniganj Formation.",
        original_value="R4",
    )
    _fact(
        db,
        doc,
        metric_kind="seam",
        seam_name="Uncorrelated Barakar seam",
        seam_status="uncorrelated",
        geological_formation="Barakar Formation",
        source_page=34,
        evidence_text="An uncorrelated seam in the Barakar Formation.",
    )
    _fact(
        db,
        doc,
        metric_kind=RESOURCE_QUANTITY,
        seam_name="R4",
        seam_status="named",
        original_value="1.67",
        original_unit="MT",
        source_page=31,
        evidence_text="Seam R4 contributes 1.67 MT of inferred coal resources.",
    )
    _fact(
        db,
        doc,
        metric_kind=BOREHOLE_DEPTH,
        borehole_id="NP-01",
        depth="142.6",
        depth_unit="m",
        depth_normalized_m=142.6,
        source_page=20,
        evidence_text="Borehole NP-01 was drilled to a depth of 142.6 m.",
        original_value="142.6",
        original_unit="m",
    )
    _fact(
        db,
        doc,
        metric_kind=SEAM_THICKNESS,
        seam_name="R4",
        seam_status="named",
        thickness="1.20",
        thickness_unit="m",
        thickness_normalized_m=1.20,
        source_page=15,
        evidence_text="Thickness of Seam R4 is 1.20 m.",
        original_value="1.20",
        original_unit="m",
    )
    _fact(
        db,
        doc,
        metric_kind=MINIMUM_WORKABLE_SEAM_THICKNESS,
        thickness="0.90",
        thickness_unit="m",
        thickness_normalized_m=0.90,
        source_page=8,
        evidence_text="Minimum workable thickness considered is 0.90 m.",
        original_value="0.90",
        original_unit="m",
    )
    # Invalid formation fragment — must not appear in explorer listings
    _fact(
        db,
        doc,
        metric_kind="formation",
        geological_formation="through the Formation",
        source_page=21,
        evidence_text="passed through the Formation boundary",
    )
    # Rejected fact — must not appear in official analytics
    _fact(
        db,
        doc,
        metric_kind=RESOURCE_QUANTITY,
        seam_name="R4",
        original_value="99.9",
        original_unit="MT",
        status=FactStatus.REJECTED.value,
        source_page=99,
        evidence_text="Rejected bogus resource 99.9 MT.",
    )
    return doc


# ── Explorer ────────────────────────────────────────────────


def test_document_summary(db_session):
    doc = _seed_basic(db_session)
    summary = geo_explorer.document_summary(db_session, doc.id)
    assert summary["fact_count"] >= 8
    assert summary["formation_count"] == 2
    assert summary["seam_count"] >= 1
    assert summary["borehole_count"] == 1
    assert summary["resource_fact_count"] >= 1
    assert summary["review_required_count"] >= 1
    assert summary["document_name"] == "alpha_geo.pdf"


def test_formation_listing_excludes_fragments(db_session):
    doc = _seed_basic(db_session)
    forms = geo_explorer.list_formations(db_session, document_id=doc.id)
    names = {f["formation_name"] for f in forms}
    assert "Raniganj Formation" in names
    assert "Barakar Formation" in names
    assert "through the Formation" not in names
    assert all(f["evidence_count"] >= 1 for f in forms)
    assert all("source_pages" in f for f in forms)


def test_seam_listing(db_session):
    doc = _seed_basic(db_session)
    seams = geo_explorer.list_seams(db_session, document_id=doc.id)
    names = {s["seam_name"] for s in seams}
    assert any("R4" in n for n in names)
    r4 = next(s for s in seams if "R4" in s["seam_name"])
    assert r4["formation"] == "Raniganj Formation"
    assert r4["resource"] == "1.67"
    assert r4["thickness"] == "1.20"  # not 0.90 workable
    assert r4["review_status"] in {"verified", "review_required"}


def test_borehole_listing(db_session):
    doc = _seed_basic(db_session)
    bhs = geo_explorer.list_boreholes(db_session, document_id=doc.id)
    assert len(bhs) == 1
    assert bhs[0]["borehole_id"] == "NP-01"
    assert bhs[0]["depth"] == "142.6"
    assert bhs[0]["depth_metric_kind"] == BOREHOLE_DEPTH


def test_fact_detail_and_provenance(db_session):
    doc = _seed_basic(db_session)
    rows = geo_explorer.query_geological_facts(db_session, document_id=doc.id, metric="resource")
    assert rows
    detail = geo_explorer.get_fact_detail(db_session, rows[0].id)
    assert detail is not None
    assert detail["provenance"]["document_id"] == doc.id
    assert detail["provenance"]["page"] is not None
    assert detail["provenance"]["evidence_text"]
    assert detail["requires_human_verification"] is True
    assert detail["verification_message"] == "Requires human verification"


def test_review_status_visible(db_session):
    doc = _seed_basic(db_session)
    overview = geo_explorer.explorer_overview(db_session, document_id=doc.id)
    assert any(f.get("requires_human_verification") for f in overview["facts"]["items"])
    assert overview["summary"]["review_required_count"] >= 1


# ── Filtering ───────────────────────────────────────────────


def test_document_filter(db_session):
    a = _seed_basic(db_session)
    b = _doc(db_session, "other.pdf")
    _fact(
        db_session,
        b,
        metric_kind="formation",
        geological_formation="Talchir Formation",
        evidence_text="Talchir Formation occurs here.",
        original_value="Talchir Formation",
    )
    forms_a = geo_explorer.list_formations(db_session, document_id=a.id)
    assert all("Talchir" not in f["formation_name"] for f in forms_a)
    forms_b = geo_explorer.list_formations(db_session, document_id=b.id)
    assert any("Talchir" in f["formation_name"] for f in forms_b)


def test_formation_seam_borehole_metric_filters(db_session):
    doc = _seed_basic(db_session)
    by_form = geo_explorer.query_geological_facts(
        db_session, document_id=doc.id, formation="Raniganj"
    )
    assert by_form
    # Direct formation rows or seam-associated rows for Raniganj
    assert any("Raniganj" in (r.geological_formation or "") for r in by_form)
    assert any(
        "Raniganj" in (r.geological_formation or "") or (r.seam_name and "R4" in r.seam_name)
        for r in by_form
    )

    by_seam = geo_explorer.query_geological_facts(
        db_session, document_id=doc.id, seam="R4"
    )
    assert by_seam
    assert all("R4" in (r.seam_name or "") for r in by_seam)

    by_bh = geo_explorer.query_geological_facts(
        db_session, document_id=doc.id, borehole="NP-01"
    )
    assert len(by_bh) >= 1
    assert all(r.borehole_id == "NP-01" for r in by_bh)

    by_metric = geo_explorer.query_geological_facts(
        db_session, document_id=doc.id, metric="resource"
    )
    assert by_metric
    assert all(
        (r.metric_kind or "") in {"resource", "resource_quantity"}
        for r in by_metric
    )


def test_combined_filters_resource_for_seam(db_session):
    doc = _seed_basic(db_session)
    rows = geo_explorer.query_geological_facts(
        db_session,
        document_id=doc.id,
        formation="Raniganj",
        seam="R4",
        metric="resource",
    )
    assert rows
    assert all("R4" in (r.seam_name or "") for r in rows)
    vals = [r.original_value for r in rows if r.original_value]
    assert "1.67" in vals
    assert "99.9" not in vals  # rejected excluded


# ── Analytics ───────────────────────────────────────────────


def test_resource_by_seam(db_session):
    doc = _seed_basic(db_session)
    res = geo_analytics.resources_by_seam(db_session, document_id=doc.id)
    assert not res["empty"]
    seams = {i["seam"] for i in res["items"]}
    assert any("R4" in s for s in seams)
    r4 = next(i for i in res["items"] if "R4" in i["seam"])
    assert r4["value"] == "1.67"
    assert r4["unit"] == "MT"
    assert r4["page"] == 31
    assert r4["fact_id"]
    assert "99.9" not in {i["value"] for i in res["items"]}


def test_formation_seam_relationship(db_session):
    doc = _seed_basic(db_session)
    dist = geo_analytics.formation_seam_distribution(db_session, document_id=doc.id)
    assert not dist["empty"]
    forms = {i["formation"]: i for i in dist["items"]}
    assert "Raniganj Formation" in forms
    seam_names = {s["seam"] for s in forms["Raniganj Formation"]["seams"]}
    assert any("R4" in s for s in seam_names)


def test_borehole_depth_analytic(db_session):
    doc = _seed_basic(db_session)
    depths = geo_analytics.borehole_depth_summary(db_session, document_id=doc.id)
    assert not depths["empty"]
    assert depths["items"][0]["borehole_id"] == "NP-01"
    assert depths["items"][0]["value"] == "142.6"
    assert depths["items"][0]["metric_kind"] == BOREHOLE_DEPTH


def test_compatible_seam_thickness_excludes_workable(db_session):
    doc = _seed_basic(db_session)
    thick = geo_analytics.seam_thickness_analytic(db_session, document_id=doc.id)
    assert not thick["empty"]
    values = {i["value"] for i in thick["items"]}
    assert "1.20" in values
    assert "0.90" not in values  # workable must not substitute


def test_empty_analytics_state(db_session):
    doc = _doc(db_session, "empty_geo.pdf")
    res = geo_analytics.resources_by_seam(db_session, document_id=doc.id)
    assert res["empty"] is True
    assert "No compatible structured evidence" in res["message"]


def test_review_required_handling_and_rejected_excluded(db_session):
    doc = _seed_basic(db_session)
    res = geo_analytics.resources_by_seam(db_session, document_id=doc.id)
    assert res["pending_verification"] is True
    assert res["official"] is False
    assert "pending human verification" in (res["message"] or "").lower()
    assert all(i["value"] != "99.9" for i in res["items"])
    assert all(i["status"] != FactStatus.REJECTED.value for i in res["items"])


def test_geological_fact_summary(db_session):
    doc = _seed_basic(db_session)
    summary = geo_analytics.geological_fact_summary(db_session, document_id=doc.id)
    assert summary["formations_identified"] == 2
    assert summary["seams_identified"] >= 1
    assert summary["boreholes_identified"] == 1
    assert summary["resources_available"] >= 1
    assert summary["documents_represented"] == 1


# ── Evidence ────────────────────────────────────────────────


def test_chart_evidence_and_page_citation(db_session):
    doc = _seed_basic(db_session)
    res = geo_analytics.resources_by_seam(db_session, document_id=doc.id)
    item = res["items"][0]
    assert item["document_id"] == doc.id
    assert item["page"] is not None
    assert item["evidence_text"]
    assert item["fact_id"]
    detail = geo_explorer.get_fact_detail(db_session, item["fact_id"])
    assert detail["provenance"]["page"] == item["page"]


def test_source_navigation_fields(db_session):
    doc = _seed_basic(db_session)
    overview = geo_explorer.explorer_overview(db_session, document_id=doc.id)
    fact = overview["facts"]["items"][0]
    assert fact["document_id"]
    assert "provenance" in fact
    assert fact["provenance"]["document_id"] == doc.id


# ── Comparison ──────────────────────────────────────────────


def test_two_document_comparison(db_session):
    a = _seed_basic(db_session)
    b = _doc(db_session, "beta_geo.pdf")
    _fact(
        db_session,
        b,
        metric_kind="formation",
        geological_formation="Talchir Formation",
        evidence_text="Talchir Formation present.",
        original_value="Talchir Formation",
    )
    _fact(
        db_session,
        b,
        metric_kind=RESOURCE_QUANTITY,
        seam_name="S1",
        seam_status="named",
        original_value="2.5",
        original_unit="MT",
        evidence_text="Seam S1 inferred resource 2.5 MT.",
        source_page=5,
    )
    cmp = geo_analytics.compare_documents(db_session, a.id, b.id)
    assert cmp["document_a"]["document_id"] == a.id
    assert cmp["document_b"]["document_id"] == b.id
    assert "not ranked" in (cmp.get("note") or "").lower()
    metrics = {c["metric"] for c in cmp["comparisons"]}
    assert "formations" in metrics
    assert "resources" in metrics
    # Evidence preserved per side
    forms = next(c for c in cmp["comparisons"] if c["metric"] == "formations")
    assert forms["document_a"]["count"] == 2
    assert forms["document_b"]["count"] == 1
    assert forms["document_a"]["evidence"][0]["document_id"] == a.id
    assert forms["document_b"]["evidence"][0]["document_id"] == b.id


def test_compare_same_document_rejected(db_session):
    doc = _seed_basic(db_session)
    cmp = geo_analytics.compare_documents(db_session, doc.id, doc.id)
    assert "error" in cmp


def test_incompatible_thickness_not_in_seam_thickness_compare_side(db_session):
    """Workable thickness must not appear as seam thickness analytic."""
    doc = _seed_basic(db_session)
    thick = geo_analytics.seam_thickness_analytic(db_session, document_id=doc.id)
    for item in thick["items"]:
        assert item["metric_kind"] == SEAM_THICKNESS
        assert item["value"] != "0.90"


# ── LLM explanation ─────────────────────────────────────────


def test_explanation_uses_supplied_evidence(db_session):
    doc = _seed_basic(db_session)
    evidence = geo_analytics.resources_by_seam(db_session, document_id=doc.id)
    result = geo_analytics.explain_analytics(
        question="Explain the resource distribution shown here.",
        evidence=evidence,
    )
    assert "1.67" in result["explanation"]
    assert result["evidence_used"]["item_count"] >= 1
    # Must not invent rejected value
    assert "99.9" not in result["explanation"]


def test_llm_cannot_invent_missing_numerical_data():
    result = geo_analytics.explain_analytics(
        question="What is the total resource?",
        evidence={"items": [], "empty": True, "message": "No compatible structured evidence available."},
    )
    assert "insufficient" in result["explanation"].lower() or "no compatible" in result["explanation"].lower()


def test_insufficient_evidence_response():
    result = geo_analytics.explain_analytics(
        question="Explain borehole depths.",
        evidence={"empty": True, "items": []},
    )
    assert "Insufficient" in result["explanation"] or "insufficient" in result["explanation"].lower()


# ── API smoke ───────────────────────────────────────────────


def test_geology_api_explorer(client, db_session):
    doc = _seed_basic(db_session)
    db_session.commit()
    res = client.get(f"/api/geology/explorer?document_id={doc.id}")
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["formation_count"] == 2
    assert body["facts"]["total"] >= 1
    names = {f["formation_name"] for f in body["formations"]}
    assert "Raniganj Formation" in names
    assert "through the Formation" not in names


def test_geology_api_analytics_and_explain(client, db_session):
    doc = _seed_basic(db_session)
    db_session.commit()
    res = client.get(f"/api/geology/analytics/resources?document_id={doc.id}")
    assert res.status_code == 200
    body = res.json()
    assert any(i["value"] == "1.67" for i in body["items"])

    expl = client.post(
        "/api/geology/analytics/explain",
        json={
            "question": "Explain the resource distribution shown here.",
            "analytic": "resources_by_seam",
            "document_id": doc.id,
        },
    )
    assert expl.status_code == 200
    assert "1.67" in expl.json()["explanation"]


def test_geology_api_compare(client, db_session):
    a = _seed_basic(db_session)
    b = _doc(db_session, "gamma.pdf")
    _fact(
        db_session,
        b,
        metric_kind="formation",
        geological_formation="Talchir Formation",
        evidence_text="Talchir Formation.",
    )
    db_session.commit()
    res = client.get(
        f"/api/geology/compare?document_id_a={a.id}&document_id_b={b.id}"
    )
    assert res.status_code == 200
    assert "not ranked" in res.json()["note"].lower()


def test_unit_normalization_mass():
    from app.geology.explorer import to_tonnes

    assert to_tonnes(1.67, "MT") == 1.67 * 1_000_000
    assert to_tonnes(1000, "kg") == 1.0
    assert to_tonnes(5, "m") is None  # unrelated unit
