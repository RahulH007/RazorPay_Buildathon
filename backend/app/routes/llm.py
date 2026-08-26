"""
RecoverOS LLM Activity

What the model actually did, derived from the ledger rather than from an
in-process counter. The ledger is the record of work, so a restart cannot
inflate or erase this, and every number here is backed by an entry a reviewer
can verify by hash.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from collections import Counter

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app import llm_cache
from app.database import SessionLocal
from app.models import AuditTrailEntry

router = APIRouter()


def build_activity(db: Session) -> dict:
    entries = db.query(AuditTrailEntry).filter(
        AuditTrailEntry.llm_model.isnot(None)
    ).all()

    by_model = Counter(e.llm_model for e in entries)
    by_action = Counter(e.action for e in entries)
    latencies = [e.llm_latency_ms for e in entries if e.llm_latency_ms is not None]

    # The rule engine handles the mapped majority. Reporting the split rather
    # than the model's count alone is the honest framing: most records never
    # need a model, and claiming otherwise is the easiest thing to disprove.
    classifications = db.query(AuditTrailEntry).filter(
        AuditTrailEntry.action.like("CLASSIFIED_%")
    ).all()
    split = Counter(e.actor for e in classifications)

    rejections = db.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "LLM_OUTPUT_REJECTED"
    ).count()

    return {
        "total_calls": len(entries),
        "by_model": dict(by_model),
        "by_action": dict(by_action),
        "total_input_tokens": sum(e.llm_input_tokens or 0 for e in entries),
        "total_output_tokens": sum(e.llm_output_tokens or 0 for e in entries),
        "mean_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "rejections": rejections,
        "classification_split": {
            "rule_engine": split.get("rule_engine", 0),
            "llm_agent": split.get("llm_agent", 0),
        },
        "cache": llm_cache.stats(),
    }


@router.get("/llm/activity")
async def llm_activity():
    db = SessionLocal()
    try:
        return build_activity(db)
    finally:
        db.close()
