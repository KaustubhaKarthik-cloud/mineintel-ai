from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.auth.deps import AuthUser, require_permission
from app.database import get_db
from app.models import Document, DocumentStatus, Topic
from app.schemas import DashboardStats, DocumentOut
from app.services import demo_data

router = APIRouter()


@router.get("", response_model=DashboardStats)
def get_dashboard(
    db: Session = Depends(get_db),
    user: AuthUser = Depends(require_permission("documents.read")),
) -> DashboardStats:
    """Live document counts; demo intelligence stats only fill gaps when DB is empty."""
    base = demo_data.get_dashboard_stats()
    docs = db.query(Document).order_by(desc(Document.created_at)).all()
    topic_count = db.query(Topic).count()
    if topic_count:
        base["topics_tracked"] = topic_count

    if docs:
        pending = sum(
            1
            for d in docs
            if d.status
            in {
                DocumentStatus.REVIEW_REQUIRED.value,
                DocumentStatus.PENDING_REVIEW.value,
            }
        )
        processing = sum(
            1
            for d in docs
            if d.status
            in {
                DocumentStatus.PROCESSING.value,
                DocumentStatus.UPLOADED.value,
            }
        )
        completed = sum(1 for d in docs if d.status == DocumentStatus.COMPLETED.value)
        recent = []
        for d in docs[:5]:
            item = DocumentOut.model_validate(d)
            recent.append(item.model_copy(update={"upload_date": d.created_at}))

        base["total_documents"] = len(docs)
        base["pending_review"] = pending
        base["approved_records"] = completed
        base["processing_queue"] = processing
        base["recent_documents"] = recent
        base["pipeline_status"] = {
            **base.get("pipeline_status", {}),
            "ingestion": "operational",
            "ocr_parsing": "operational",
        }

    return DashboardStats(**base)
