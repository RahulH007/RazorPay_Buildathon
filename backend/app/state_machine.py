"""
RecoverOS State Machine
FSM managing payment recovery lifecycle: INGESTED → DIAGNOSED → INTERVENING → RECOVERED/FAILED_STOPPED

Every transition and every intermediate action is written through the ledger
(app/ledger.py), so the audit trail is a tamper-evident hash chain rather than
an ordinary table. Callers keep the same signatures they always had.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import ledger
from app.models import PaymentFailureRecord, AuditTrailEntry
from app.websocket_manager import manager


# Valid state transitions
VALID_TRANSITIONS = {
    "INGESTED": ["DIAGNOSED"],
    # DIAGNOSED -> RECOVERED covers a payment captured without any
    # intervention: the holdout control arm, and the real case of a
    # customer retrying while we are still deciding.
    "DIAGNOSED": ["INTERVENING", "RECOVERED", "FAILED_STOPPED"],
    "INTERVENING": ["RECOVERED", "FAILED_STOPPED"],
    "RECOVERED": [],       # Terminal state
    "FAILED_STOPPED": [],  # Terminal state
}

# Transition triggers for audit logging
TRANSITION_TRIGGERS = {
    ("INGESTED", "DIAGNOSED"): "classify",
    ("DIAGNOSED", "INTERVENING"): "start_recovery",
    ("DIAGNOSED", "RECOVERED"): "captured_without_intervention",
    ("DIAGNOSED", "FAILED_STOPPED"): "hard_decline",
    ("INTERVENING", "RECOVERED"): "payment_captured",
    ("INTERVENING", "FAILED_STOPPED"): "timeout_or_opt_out",
}


def validate_transition(from_state: str, to_state: str) -> bool:
    """Check if a state transition is valid."""
    return to_state in VALID_TRANSITIONS.get(from_state, [])


def _ledger_kwargs(llm_metadata: dict | None) -> dict:
    """
    Translate the caller-facing LLM metadata dict into ledger fields.

    Confidence arrives as a 0.0-1.0 float and is stored as integer basis
    points, because floats must never enter a hash preimage.
    """
    if not llm_metadata:
        return {}

    confidence = llm_metadata.get("confidence")
    return {
        "llm_model": llm_metadata.get("model"),
        "llm_input_tokens": llm_metadata.get("input_tokens"),
        "llm_output_tokens": llm_metadata.get("output_tokens"),
        "llm_latency_ms": llm_metadata.get("latency_ms"),
        "llm_confidence_bp": None if confidence is None else round(confidence * 10000),
    }


async def transition_state(
    db: Session,
    record: PaymentFailureRecord,
    to_state: str,
    actor: str = "system",
    details: str = "",
    cost_paise: int = 0,
    llm_metadata: dict = None,
) -> bool:
    """
    Transition a payment record to a new state.
    Appends a ledger entry and broadcasts a WebSocket event.
    Returns True if transition was successful.
    """
    from_state = record.recovery_state

    if not validate_transition(from_state, to_state):
        raise ValueError(
            f"Invalid transition: {from_state} → {to_state} for {record.payment_id}"
        )

    # Update the record state
    record.recovery_state = to_state
    record.updated_at = datetime.now(timezone.utc)

    # Determine the trigger/action name
    trigger = TRANSITION_TRIGGERS.get((from_state, to_state), f"{from_state}_TO_{to_state}")
    action = f"STATE_{from_state}_TO_{to_state}"

    ledger.append_entry(
        db,
        payment_id=record.payment_id,
        batch_id=record.batch_id,
        action=action,
        actor=actor,
        details=details or f"Transition triggered by: {trigger}",
        cost_paise=cost_paise,
        **_ledger_kwargs(llm_metadata),
    )
    db.refresh(record)

    # Broadcast WebSocket event
    try:
        await manager.send_state_change(
            payment_id=record.payment_id,
            from_state=from_state,
            to_state=to_state,
            details={
                "actor": actor,
                "trigger": trigger,
                "details": details,
                "amount": record.amount,
                "failure_class": record.failure_class,
                "customer_name": record.customer_name,
                "recovery_channel": record.recovery_channel,
            },
        )
    except Exception as e:
        # Don't fail the transition if WebSocket broadcast fails
        print(f"[WARN] WebSocket broadcast failed: {e}")

    return True


def log_audit(
    db: Session,
    record: PaymentFailureRecord,
    action: str,
    actor: str = "system",
    details: str = "",
    cost_paise: int = 0,
    llm_metadata: dict = None,
) -> AuditTrailEntry:
    """
    Append a ledger entry without a state transition.
    Used for intermediate actions (e.g., classification, retry attempt).
    """
    return ledger.append_entry(
        db,
        payment_id=record.payment_id,
        batch_id=record.batch_id,
        action=action,
        actor=actor,
        details=details,
        cost_paise=cost_paise,
        **_ledger_kwargs(llm_metadata),
    )
