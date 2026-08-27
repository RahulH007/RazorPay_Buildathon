"""
RecoverOS Live Event Adapter

The boundary between a signed Razorpay webhook and this system's own model.

Two jobs, kept separate on purpose:

  normalize_razorpay_payment_failed(payload) -- pure translation, no database,
      no side effects. It either returns a complete normalized dict or None,
      so a malformed webhook is rejected before anything durable is written.

  ingest_and_process(db, normalized, batch_id=None) -- the stateful half.

Why this does not reuse recovery_simulator.ingest_record: that function resets
an existing record's recovery_state, failure_class and recovery_channel so a
batch can be re-run over the same dataset. Correct for a simulation, wrong for
a webhook. Razorpay retries delivery, and re-running the pipeline on a retry
would re-classify a record, re-open a settled one, and append a second
RECORD_INGESTED entry to an append-only ledger. Here a repeat delivery is a
true no-op.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from typing import Optional

from sqlalchemy.orm import Session

from app.classifier import RULE_MAP, classify
from app.models import AuditTrailEntry, PaymentFailureRecord
from app.razorpay_client import LIVE_SOURCE
from app.recovery_actions import execute_recovery
from app.state_machine import log_audit

# Used when Razorpay gives us no name. Deliberately obvious rather than a
# plausible-looking invention: a fabricated customer name in an audit trail is
# worse than an honest placeholder.
UNKNOWN_CUSTOMER_NAME = "Razorpay Customer"


def normalize_razorpay_payment_failed(payload: dict) -> Optional[dict]:
    """
    Translate a payment.failed webhook body into PaymentFailureRecord fields.

    Returns None when the payload cannot identify a payment or a merchant.
    Those two are the identity of the record; without them there is nothing
    coherent to store, and guessing would put fiction into the ledger.
    """
    if not isinstance(payload, dict):
        return None

    entity = (
        payload.get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )
    if not isinstance(entity, dict):
        return None

    payment_id = entity.get("id")
    if not payment_id:
        return None

    amount = entity.get("amount")
    if not isinstance(amount, int):
        return None

    # Razorpay's own account identifier. The schema requires a merchant, and
    # inventing one would make the record untraceable back to its origin.
    merchant_id = payload.get("account_id") or entity.get("merchant_id")
    if not merchant_id:
        return None

    error = entity.get("error", {}) if isinstance(entity.get("error"), dict) else {}
    notes = entity.get("notes", {}) if isinstance(entity.get("notes"), dict) else {}

    return {
        "payment_id": payment_id,
        "amount": amount,
        "currency": entity.get("currency") or "INR",
        "method": entity.get("method") or "unknown",
        "merchant_id": str(merchant_id),
        "invoice_id": entity.get("invoice_id"),
        "customer_name": notes.get("customer_name") or UNKNOWN_CUSTOMER_NAME,
        "customer_email": entity.get("email"),
        "customer_phone": entity.get("contact") or "",
        # Razorpay puts these at the entity root on payment.failed, and inside
        # `error` on some payloads. Take either.
        "error_source": entity.get("error_source") or error.get("source"),
        "error_step": entity.get("error_step") or error.get("step"),
        "error_reason": entity.get("error_reason") or error.get("reason") or "unknown",
        "error_description": entity.get("error_description") or error.get("description"),
        "source": LIVE_SOURCE,
        "recovery_state": "INGESTED",
    }


async def ingest_and_process(
    db: Session,
    normalized: dict,
    batch_id: Optional[str] = None,
) -> dict:
    """
    Persist a normalized live failure, classify it, and attempt recovery.

    Idempotent by payment id: a repeat delivery returns the existing record
    untouched. Razorpay retries on any non-2xx and on timeouts, so this path
    will be entered more than once for the same payment as a matter of course.
    """
    payment_id = normalized["payment_id"]

    existing = db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.payment_id == payment_id
    ).first()

    if existing:
        # A true no-op. No second RECORD_INGESTED entry, no re-classification,
        # no further recovery attempt, no state reset.
        return {
            "status": "duplicate",
            "payment_id": payment_id,
            "recovery_state": existing.recovery_state,
            "failure_class": existing.failure_class,
        }

    record = PaymentFailureRecord(batch_id=batch_id, **normalized)
    db.add(record)
    db.commit()
    db.refresh(record)

    log_audit(
        db, record,
        action="RECORD_INGESTED",
        actor="system",
        details=(
            f"Live payment.failed from Razorpay: {record.payment_id}, "
            f"Rs {record.amount / 100:,.2f} via {record.method}. "
            f"error.reason={record.error_reason}"
        ),
    )

    failure_class = await classify(db, record)

    # --- Unmapped-reason safety gate ---------------------------------------
    #
    # RULE_MAP is the set of error codes a human has explicitly approved for
    # automatic recovery. Razorpay's live vocabulary is wider than the seeded
    # dataset's - "payment_failed", "payment_cancelled" and others arrive from
    # real traffic and are not in it.
    #
    # This is a policy boundary, not a patch for a weak classifier. The
    # diagnosis may well be correct; the point is that nobody has decided this
    # system should spend money and message a stranger on the strength of an
    # error code it has never been told how to treat. Classification still runs,
    # so the record is visible and diagnosable - only the automatic action is
    # withheld.
    #
    # Scoped to live records by source. Synthetic records reach this function
    # never, and the simulator's own path is untouched.
    if record.source == LIVE_SOURCE and record.error_reason not in RULE_MAP:
        classification = db.query(AuditTrailEntry).filter(
            AuditTrailEntry.payment_id == record.payment_id,
            AuditTrailEntry.action.like("CLASSIFIED_%"),
        ).order_by(AuditTrailEntry.sequence_no.desc()).first()

        log_audit(
            db, record,
            action="UNMAPPED_REASON_HELD_FOR_REVIEW",
            actor="system",
            details=(
                f"WHY_WE_DIDNT_ACT: error.reason={record.error_reason!r} arrived "
                f"from a live Razorpay webhook and is not in RULE_MAP, the set of "
                f"codes approved for automatic recovery. "
                f"Classified as {record.failure_class or 'unknown'} by "
                f"{classification.actor if classification else 'unknown'}. "
                f"The record is ingested, classified and open for review; no "
                f"policy decision was taken, no channel was used and no money "
                f"was spent."
            ),
            cost_paise=0,
        )
        db.commit()
        db.refresh(record)

        return {
            "status": "held_for_review",
            "payment_id": payment_id,
            "failure_class": failure_class.value if failure_class else None,
            "recovery_state": record.recovery_state,
            "reason": "error_reason not in RULE_MAP",
        }

    # A hard decline is terminal at classification; there is nothing to execute.
    if record.recovery_state != "FAILED_STOPPED":
        await execute_recovery(db, record, source=LIVE_SOURCE)

    db.commit()
    db.refresh(record)

    return {
        "status": "ingested",
        "payment_id": payment_id,
        "failure_class": failure_class.value if failure_class else None,
        "recovery_state": record.recovery_state,
    }
