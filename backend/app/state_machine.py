"""
RecoverOS State Machine
FSM managing payment recovery lifecycle: INGESTED → DIAGNOSED → INTERVENING → RECOVERED/FAILED_STOPPED
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import PaymentFailureRecord, AuditTrailEntry
from app.websocket_manager import manager


# Valid state transitions
VALID_TRANSITIONS = {
    "INGESTED": ["DIAGNOSED"],
    "DIAGNOSED": ["INTERVENING", "FAILED_STOPPED"],
    "INTERVENING": ["RECOVERED", "FAILED_STOPPED"],
    "RECOVERED": [],       # Terminal state
    "FAILED_STOPPED": [],  # Terminal state
}

# Transition triggers for audit logging
TRANSITION_TRIGGERS = {
    ("INGESTED", "DIAGNOSED"): "classify",
    ("DIAGNOSED", "INTERVENING"): "start_recovery",
    ("DIAGNOSED", "FAILED_STOPPED"): "hard_decline",
    ("INTERVENING", "RECOVERED"): "payment_captured",
    ("INTERVENING", "FAILED_STOPPED"): "timeout_or_opt_out",
}


def validate_transition(from_state: str, to_state: str) -> bool:
    """Check if a state transition is valid."""
    return to_state in VALID_TRANSITIONS.get(from_state, [])


async def transition_state(
    db: Session,
    record: PaymentFailureRecord,
    to_state: str,
    actor: str = "system",
    details: str = "",
    cost: float = 0.0,
    llm_metadata: dict = None,
) -> bool:
    """
    Transition a payment record to a new state.
    Writes an audit trail entry and broadcasts a WebSocket event.
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

    # Create audit trail entry
    audit_entry = AuditTrailEntry(
        payment_id=record.payment_id,
        timestamp=datetime.now(timezone.utc),
        action=action,
        actor=actor,
        details=details or f"Transition triggered by: {trigger}",
        cost_incurred_inr=cost,
    )

    # Add LLM metadata if present
    if llm_metadata:
        audit_entry.llm_model = llm_metadata.get("model")
        audit_entry.llm_input_tokens = llm_metadata.get("input_tokens")
        audit_entry.llm_output_tokens = llm_metadata.get("output_tokens")
        audit_entry.llm_latency_ms = llm_metadata.get("latency_ms")
        audit_entry.llm_confidence = llm_metadata.get("confidence")

    db.add(audit_entry)
    db.commit()
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
    cost: float = 0.0,
    llm_metadata: dict = None,
) -> AuditTrailEntry:
    """
    Log an audit trail entry without a state transition.
    Used for intermediate actions (e.g., classification, retry attempt).
    """
    entry = AuditTrailEntry(
        payment_id=record.payment_id,
        timestamp=datetime.now(timezone.utc),
        action=action,
        actor=actor,
        details=details,
        cost_incurred_inr=cost,
    )

    if llm_metadata:
        entry.llm_model = llm_metadata.get("model")
        entry.llm_input_tokens = llm_metadata.get("input_tokens")
        entry.llm_output_tokens = llm_metadata.get("output_tokens")
        entry.llm_latency_ms = llm_metadata.get("latency_ms")
        entry.llm_confidence = llm_metadata.get("confidence")

    db.add(entry)
    db.commit()
    return entry
