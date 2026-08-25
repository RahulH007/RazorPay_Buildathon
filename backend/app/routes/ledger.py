"""
RecoverOS Ledger Routes
GET /api/ledger/verify — recompute and verify the entire hash chain
GET /api/ledger/head   — current chain head hash and entry count
"""

from fastapi import APIRouter

from app import ledger as ledger_mod
from app.database import SessionLocal
from app.models import AuditTrailEntry
from sqlalchemy import func

router = APIRouter()


@router.get("/ledger/verify")
async def verify_ledger():
    """
    Walk the full chain and check every invariant:
    content hashes, prev_hash linkage, and sequence contiguity.
    """
    db = SessionLocal()
    try:
        result = ledger_mod.verify_chain(db)
        return result.to_dict()
    finally:
        db.close()


@router.get("/ledger/head")
async def ledger_head():
    """Current chain head — the single value that fingerprints the whole ledger."""
    db = SessionLocal()
    try:
        head = ledger_mod.get_head(db)
        total_cost_paise = db.query(func.sum(AuditTrailEntry.cost_paise)).scalar() or 0

        if head is None:
            return {
                "head_hash": None,
                "sequence_no": None,
                "entries": 0,
                "total_cost_paise": 0,
                "genesis_prev_hash": ledger_mod.GENESIS_PREV_HASH,
                "preimage_version": ledger_mod.PREIMAGE_VERSION,
            }

        return {
            "head_hash": head.entry_hash,
            "sequence_no": head.sequence_no,
            "entries": head.sequence_no + 1,
            "last_action": head.action,
            "last_timestamp": ledger_mod.us_to_iso(head.timestamp_us),
            "total_cost_paise": total_cost_paise,
            "total_cost_inr": total_cost_paise / 100.0,
            "genesis_prev_hash": ledger_mod.GENESIS_PREV_HASH,
            "preimage_version": ledger_mod.PREIMAGE_VERSION,
        }
    finally:
        db.close()
