"""
RecoverOS Classifier
Rule Engine (Fast Path) for deterministic error code classification
+ LLM router (Slow Path) for ambiguous cases.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
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
    Slow Path: the rule engine has no entry for this error, so ask the model
    what actually went wrong.

    Previously this called parse_customer_reply - a prompt written to read
    customer messages - with a bank error string, then mapped reply intents
    onto failure classes. An unrecognised error code was therefore usually
    killed as a hard decline by a function that was never asked the right
    question.
    """
    from app.llm_agent import diagnose_failure

    try:
        diagnosis, metadata = await diagnose_failure(record)
    except Exception as e:
        # A model or cache failure must never silently reclassify a payment.
        log_audit(
            db, record,
            action="ESCALATED_TO_HUMAN",
            actor="system",
            details=f"Diagnosis unavailable ({type(e).__name__}: {str(e)[:200]}). "
                    f"No automated action taken on this record.",
        )
        return FailureClass.HARD_DECLINE, "system", f"Diagnosis unavailable: {type(e).__name__}"

    if diagnosis.confidence < CONFIDENCE_THRESHOLD:
        log_audit(
            db, record,
            action="ESCALATED_TO_HUMAN",
            actor="llm_agent",
            details=f"Confidence {diagnosis.confidence:.2f} below threshold "
                    f"{CONFIDENCE_THRESHOLD}. Model read: "
                    f"{diagnosis.technical_explanation}",
            llm_metadata=metadata,
        )
        return (
            FailureClass.HARD_DECLINE,
            "llm_agent",
            f"Low confidence ({diagnosis.confidence:.2f}) - escalated to human",
        )

    log_audit(
        db, record,
        action="FAILURE_DIAGNOSED_LLM",
        actor="llm_agent",
        details=f"{diagnosis.technical_explanation} "
                f"Suggested action (recorded, not executed): {diagnosis.suggested_action}",
        llm_metadata=metadata,
    )

    failure_class = FailureClass(diagnosis.root_cause_class)
    return (
        failure_class,
        "llm_agent",
        f"Diagnosed as {failure_class.value} (confidence {diagnosis.confidence:.2f})",
    )
