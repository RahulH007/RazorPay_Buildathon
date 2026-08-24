"""
RecoverOS Classifier
Rule Engine (Fast Path) for deterministic error code classification
+ LLM router (Slow Path) for ambiguous cases.
"""

from sqlalchemy.orm import Session

from app.models import PaymentFailureRecord
from app.schemas import FailureClass
from app.state_machine import transition_state, log_audit
from app.config import RECOVERY_CHANNELS, CONFIDENCE_THRESHOLD


# --- Rule Engine: Fast Path ---
# Maps known Razorpay error codes to failure classes deterministically
RULE_MAP = {
    "bank_technical_error": FailureClass.TRANSIENT_TECHNICAL,
    "gateway_error": FailureClass.TRANSIENT_TECHNICAL,
    "authentication_failed": FailureClass.AUTH_FRICTION,
    "incorrect_otp": FailureClass.AUTH_FRICTION,
    "mandate_insufficient_funds": FailureClass.MANDATE_BALANCE,
    "card_expired": FailureClass.MANDATE_BALANCE,
    "invoice_overdue_15d": FailureClass.B2B_RECEIVABLE,
    "compliance_violation": FailureClass.HARD_DECLINE,
    "debit_instrument_blocked": FailureClass.HARD_DECLINE,
}


async def classify(db: Session, record: PaymentFailureRecord) -> FailureClass:
    """
    Classify a payment failure into one of 5 failure classes.
    
    Fast Path: Uses deterministic rule lookup for known error codes.
    Slow Path: Falls back to LLM for ambiguous/unknown error reasons.
    """
    error_reason = record.error_reason

    if error_reason in RULE_MAP:
        # Fast Path: deterministic classification
        failure_class = RULE_MAP[error_reason]
        actor = "rule_engine"
        details = f"Matched error.reason='{error_reason}' to {failure_class.value} via rule engine"
    else:
        # Slow Path: LLM classification for ambiguous cases
        failure_class, actor, details = await llm_classify(db, record)

    # Update record with classification
    record.failure_class = failure_class.value
    record.recovery_channel = RECOVERY_CHANNELS.get(failure_class.value)

    # Log classification audit entry
    log_audit(
        db, record,
        action=f"CLASSIFIED_{failure_class.value}",
        actor=actor,
        details=details,
    )

    # Transition from INGESTED → DIAGNOSED
    await transition_state(
        db, record,
        to_state="DIAGNOSED",
        actor=actor,
        details=f"Classification: {failure_class.value} — {details}",
    )

    # Hard Decline: immediately transition to FAILED_STOPPED
    if failure_class == FailureClass.HARD_DECLINE:
        await transition_state(
            db, record,
            to_state="FAILED_STOPPED",
            actor=actor,
            details=f"WHY_WE_DIDNT_ACT: {record.error_description or error_reason}. "
                    f"Hard decline — zero retries, no customer outreach. "
                    f"Reason: {error_reason}",
        )

    db.commit()
    return failure_class


async def llm_classify(db: Session, record: PaymentFailureRecord):
    """
    Slow Path: Use LLM for ambiguous failure reasons.
    Falls back to HARD_DECLINE with escalation if confidence is too low.
    """
    try:
        from app.llm_agent import parse_customer_reply

        result = await parse_customer_reply(record, record.error_description or record.error_reason)

        if result.confidence < CONFIDENCE_THRESHOLD:
            # Low confidence → escalate to human review
            log_audit(
                db, record,
                action="ESCALATED_TO_HUMAN",
                actor="llm_agent",
                details=f"Confidence {result.confidence:.2f} below threshold {CONFIDENCE_THRESHOLD}",
                llm_metadata={
                    "model": "gemini-2.0-flash",
                    "confidence": result.confidence,
                },
            )
            return FailureClass.HARD_DECLINE, "llm_agent", f"Low confidence ({result.confidence:.2f}) — escalated to human"

        # Map LLM intent to failure class
        failure_class = map_intent_to_class(result.intent)
        return failure_class, "llm_agent", f"LLM classified as {failure_class.value} (confidence: {result.confidence:.2f})"

    except Exception as e:
        # If LLM fails, treat as hard decline for safety
        return FailureClass.HARD_DECLINE, "system", f"LLM classification failed: {str(e)}"


def map_intent_to_class(intent: str) -> FailureClass:
    """Map an LLM-parsed intent to a failure class."""
    INTENT_MAP = {
        "will_pay": FailureClass.AUTH_FRICTION,
        "dispute": FailureClass.HARD_DECLINE,
        "opt_out": FailureClass.HARD_DECLINE,
        "request_delay": FailureClass.MANDATE_BALANCE,
        "unclear": FailureClass.HARD_DECLINE,
    }
    return INTENT_MAP.get(intent, FailureClass.HARD_DECLINE)
