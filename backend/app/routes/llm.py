"""
RecoverOS LLM Activity

What the model actually did, derived from the ledger rather than from an
in-process counter. The ledger is the record of work, so a restart cannot
inflate or erase this, and every number here is backed by an entry a reviewer
can verify by hash.

Everything is scoped to the batches the current records belong to. The ledger
is append-only, so re-running a batch adds entries rather than replacing them:
summing the whole table made this endpoint report every run ever performed
(342 classifications across six batches of 65 records, 201 rejected messages),
which read as one enormous run rather than the current one. metrics.py already
scopes channel spend the same way, and for the same reason.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from collections import Counter

from fastapi import APIRouter
from sqlalchemy.orm import Session

from app import ledger, llm_cache
from app.database import SessionLocal
from app.models import AuditTrailEntry, PaymentFailureRecord

router = APIRouter()

# Actions where the model produced something a person would want to read back.
INTERPRETATION_ACTIONS = (
    "FAILURE_DIAGNOSED_LLM",
    "CUSTOMER_REPLY_PARSED",
    "PROMISE_TO_PAY_RECORDED",
    "ESCALATED_TO_HUMAN",
    "LLM_OUTPUT_REJECTED",
    "VOICE_SCRIPT_GENERATED",
    "WHATSAPP_LINK_SENT",
)


def active_batch_ids(db: Session) -> set:
    """The batches the records currently on the board belong to."""
    return {
        r.batch_id
        for r in db.query(PaymentFailureRecord.batch_id).distinct()
        if r.batch_id
    }


def _scoped(db: Session, batches: set):
    query = db.query(AuditTrailEntry)
    if batches:
        query = query.filter(AuditTrailEntry.batch_id.in_(batches))
    return query


def build_activity(db: Session, limit: int = 25) -> dict:
    batches = active_batch_ids(db)

    entries = _scoped(db, batches).filter(AuditTrailEntry.llm_model.isnot(None)).all()

    by_model = Counter(e.llm_model for e in entries)
    by_action = Counter(e.action for e in entries)
    latencies = [e.llm_latency_ms for e in entries if e.llm_latency_ms is not None]

    # The rule engine handles the mapped majority. Reporting the split rather
    # than the model's count alone is the honest framing: most records never
    # need a model, and claiming otherwise is the easiest thing to disprove.
    classifications = _scoped(db, batches).filter(
        AuditTrailEntry.action.like("CLASSIFIED_%")
    ).all()
    split = Counter(e.actor for e in classifications)

    rejections = _scoped(db, batches).filter(
        AuditTrailEntry.action == "LLM_OUTPUT_REJECTED"
    ).count()

    # What the model read, and what it returned. Ordered newest first so the
    # panel shows the most recent reasoning without paging.
    readable = (
        _scoped(db, batches)
        .filter(AuditTrailEntry.action.in_(INTERPRETATION_ACTIONS))
        .order_by(AuditTrailEntry.sequence_no.desc())
        .limit(limit)
        .all()
    )

    interpretations = [
        {
            "sequence_no": e.sequence_no,
            "payment_id": e.payment_id,
            "action": e.action,
            "actor": e.actor,
            "details": e.details,
            "timestamp": ledger.us_to_iso(e.timestamp_us),
            "entry_hash": e.entry_hash,
            "model": e.llm_model,
            "latency_ms": e.llm_latency_ms,
            "input_tokens": e.llm_input_tokens,
            "output_tokens": e.llm_output_tokens,
            # Confidence is stored as integer basis points so it can enter the
            # hash preimage; rendered back to a fraction only here.
            "confidence": (
                e.llm_confidence_bp / 10000 if e.llm_confidence_bp is not None else None
            ),
        }
        for e in readable
    ]

    return {
        "batches_counted": sorted(batches),
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
        "interpretations": interpretations,
        "cache": llm_cache.stats(),
    }


@router.get("/llm/activity")
async def llm_activity(limit: int = 25):
    db = SessionLocal()
    try:
        return build_activity(db, limit=limit)
    finally:
        db.close()
