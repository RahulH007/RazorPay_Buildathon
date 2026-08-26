"""
RecoverOS Guardrails Engine
Compliance & safety checks: opt-out detection, retry caps, CAC ceiling, fraud halt.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import re
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import PaymentFailureRecord, AuditTrailEntry
from app.config import MAX_RETRIES, CAC_CEILING_PERCENT


# --- Opt-Out Detection ---
# Bilingual stop phrases: English + Hindi/Hinglish.
#
# Bare negation is deliberately excluded. The earlier patterns matched \bno\b
# and \bnahi\b, which fire on "I have no money right now, will pay tomorrow"
# and "abhi nahi, kal karunga" — both payment intent, not opt-out. Suppressing
# a customer who was about to pay is the most expensive false positive here,
# so a stop signal must be an unambiguous phrase.
OPT_OUT_PATTERNS = [
    # English
    r"\bstop\b",
    r"\bunsubscribe\b",
    r"\bopt.?out\b",
    r"\bremove me\b",
    r"\bdon'?t (contact|call|message|text)\b",
    r"\bno more (calls|messages|texts|reminders)\b",
    r"\bleave me alone\b",
    # Hindi / Hinglish — complete stop phrases, never bare negation
    r"\bmat karo\b",
    r"\bmat bhejo\b",
    r"\bmat call karo\b",
    r"\bband karo\b",
    r"\bband kar do\b",
    r"\bnahi chahiye\b",
    r"\bcall mat\b",
    r"\bpareshan mat\b",
    r"\bhatao\b",
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


# Actions that count as a customer-facing or bank-facing recovery attempt.
# Matched exactly rather than by substring: the previous LIKE "%RETRY%" also
# matched state-transition rows, making the count unpredictable.
ATTEMPT_ACTIONS = (
    "RETRY_SILENT_ATTEMPT",
    "WHATSAPP_LINK_SENT",
    "MANDATE_RESEQUENCED",
    "VOICE_CALL_INITIATED",
)


def count_attempts(db: Session, record: PaymentFailureRecord) -> int:
    """
    Count recovery attempts made against this record *in the current batch*.

    Scoping to batch_id is essential. The ledger is append-only, so a re-run
    adds entries rather than replacing them; counting across all time meant
    that by the fourth demo run every TRANSIENT_TECHNICAL record tripped the
    cap on stale history and died instantly. The cap must measure this
    episode, not the record's entire recorded past.
    """
    query = db.query(AuditTrailEntry).filter(
        AuditTrailEntry.payment_id == record.payment_id,
        AuditTrailEntry.action.in_(ATTEMPT_ACTIONS),
    )
    if record.batch_id:
        query = query.filter(AuditTrailEntry.batch_id == record.batch_id)
    return query.count()


def spend_paise(db: Session, record: PaymentFailureRecord) -> int:
    """Total spent on this record in the current batch, in paise."""
    query = db.query(func.sum(AuditTrailEntry.cost_paise)).filter(
        AuditTrailEntry.payment_id == record.payment_id,
    )
    if record.batch_id:
        query = query.filter(AuditTrailEntry.batch_id == record.batch_id)
    return query.scalar() or 0


def cac_ceiling_paise(record: PaymentFailureRecord) -> int:
    """The most we may spend recovering this payment, in paise."""
    return record.amount * CAC_CEILING_PERCENT // 100


def check_retry_cap(db: Session, record: PaymentFailureRecord) -> bool:
    """
    True when the attempt cap has been reached and recovery should halt.
    """
    return count_attempts(db, record) >= MAX_RETRIES


def check_cac_ceiling(db: Session, record: PaymentFailureRecord) -> bool:
    """
    Check if total recovery cost exceeds the CAC ceiling (15% of invoice GMV).
    Returns True if the ceiling has been breached (should halt).

    Pure integer arithmetic: cross-multiplying instead of dividing keeps this
    exact, where a float percentage would round at the boundary.
    """
    return spend_paise(db, record) >= cac_ceiling_paise(record)


def would_breach_cac(db: Session, record: PaymentFailureRecord, cost_paise: int) -> bool:
    """
    True when spending `cost_paise` on the next action would breach the ceiling.

    Checked prospectively rather than after the fact. A retrospective check can
    only notice a breach that has already happened, which is precisely why the
    original ceiling never stopped anything: it ran once, before any spend
    existed, and so was always comparing zero against the limit.
    """
    return spend_paise(db, record) + cost_paise > cac_ceiling_paise(record)


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
