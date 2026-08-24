"""
RecoverOS Guardrails Engine
Compliance & safety checks: opt-out detection, retry caps, CAC ceiling, fraud halt.
"""

import re
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import PaymentFailureRecord, AuditTrailEntry
from app.config import MAX_RETRIES, CAC_CEILING_PERCENT


# --- Opt-Out Detection ---
# Bilingual: English + Hindi/Hinglish stop phrases
OPT_OUT_PATTERNS = [
    r"\bstop\b", r"\bcancel\b", r"\bunsubscribe\b", r"\bno\b",
    r"\bmat karo\b", r"\bband karo\b", r"\bnahi chahiye\b",
    r"\bruk jao\b", r"\bband kar do\b", r"\bmat bhejo\b",
    r"\bhatao\b", r"\bnahi\b", r"\bopt.?out\b",
]


def check_opt_out(message: str) -> bool:
    """
    Scan a customer message for opt-out keywords.
    Supports English and Hindi/Hinglish phrases.
    Returns True if an opt-out intent is detected.
    """
    if not message:
        return False
    message_lower = message.lower().strip()
    for pattern in OPT_OUT_PATTERNS:
        if re.search(pattern, message_lower):
            return True
    return False


def check_retry_cap(db: Session, record: PaymentFailureRecord) -> bool:
    """
    Check if a record has exceeded the maximum retry limit.
    Counts audit entries with RETRY in the action name.
    Returns True if the cap has been reached (should halt).
    """
    retry_count = db.query(AuditTrailEntry).filter(
        AuditTrailEntry.payment_id == record.payment_id,
        AuditTrailEntry.action.like("%RETRY%"),
    ).count()
    return retry_count >= MAX_RETRIES


def check_cac_ceiling(db: Session, record: PaymentFailureRecord) -> bool:
    """
    Check if total recovery cost exceeds the CAC ceiling (15% of invoice GMV).
    Returns True if the ceiling has been breached (should halt).
    """
    total_cost = db.query(func.sum(AuditTrailEntry.cost_incurred_inr)).filter(
        AuditTrailEntry.payment_id == record.payment_id,
    ).scalar() or 0.0

    # Amount is in paise; convert to INR for comparison
    amount_inr = record.amount / 100.0
    ceiling = amount_inr * CAC_CEILING_PERCENT / 100.0

    return total_cost >= ceiling


def check_fraud_flag(record: PaymentFailureRecord) -> bool:
    """
    Check if the record is flagged as a hard decline / fraud.
    Returns True if the record should not be contacted.
    """
    return record.failure_class == "HARD_DECLINE"


def run_all_guards(
    db: Session,
    record: PaymentFailureRecord,
    message: str = None,
) -> tuple[bool, str | None]:
    """
    Run all guardrail checks in sequence.
    
    Returns:
        (allowed: bool, halt_reason: str | None)
        - allowed=True: all guards passed, recovery action can proceed
        - allowed=False: at least one guard triggered, halt_reason explains why
    """
    # 1. Fraud / Hard Decline check
    if check_fraud_flag(record):
        return False, "FRAUD_FLAG: Record classified as HARD_DECLINE — zero retries, no customer outreach"

    # 2. Opt-out check (if customer message provided)
    if message and check_opt_out(message):
        return False, f"OPT_OUT: Customer message matched opt-out pattern: '{message[:100]}'"

    # 3. Retry cap check
    if check_retry_cap(db, record):
        return False, f"RETRY_CAP: Maximum {MAX_RETRIES} retries exceeded for {record.payment_id}"

    # 4. CAC ceiling check
    if check_cac_ceiling(db, record):
        return False, f"CAC_CEILING: Recovery cost exceeds {CAC_CEILING_PERCENT}% of invoice GMV (₹{record.amount / 100:.2f})"

    return True, None
