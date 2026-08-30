"""
RecoverOS Settlement Verification
Matches incoming payment.captured webhooks to recovery records.
Handles settlement timeouts for unresolved records.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app import idempotency
from app.models import PaymentFailureRecord, AuditTrailEntry, RazorpayPaymentLink
from app.state_machine import transition_state, log_audit
from app.config import SETTLEMENT_TIMEOUT_MINUTES
from app.websocket_manager import manager


def _extract_payment_link_id(webhook_data: dict) -> str | None:
    """
    Read a Payment Link id out of a webhook body, if one is genuinely there.

    Razorpay's payment.captured entity does not reliably carry the link id, so
    this returns None rather than reconstructing one. Guessing which link a
    captured payment belongs to - by amount, by recency, by anything - would
    let one customer's payment recover a different customer's record, which is
    the worst failure this system could have.
    """
    if not isinstance(webhook_data, dict):
        return None

    container = webhook_data.get("payload", {})
    if not isinstance(container, dict):
        return None

    link_entity = container.get("payment_link", {})
    if isinstance(link_entity, dict):
        entity = link_entity.get("entity", {})
        if isinstance(entity, dict) and entity.get("id"):
            return entity["id"]

    payment_entity = container.get("payment", {})
    if isinstance(payment_entity, dict):
        entity = payment_entity.get("entity", {})
        if isinstance(entity, dict) and entity.get("payment_link_id"):
            return entity["payment_link_id"]

    return None


def _payment_entity(webhook_data: dict) -> dict:
    if not isinstance(webhook_data, dict):
        return {}
    entity = webhook_data.get("payload", {}).get("payment", {}).get("entity", {})
    return entity if isinstance(entity, dict) else {}


async def _settle_via_payment_link(
    db: Session,
    link: RazorpayPaymentLink,
    new_payment_id: str,
    amount: int,
    currency: str,
    notes: dict,
) -> dict:
    """
    The single settlement core for both payment_link.paid and payment.captured.

    `link` is the trust anchor: this system created that row when it created
    the link at Razorpay, so it - not anything in the webhook body - decides
    which record a payment belongs to and how much it should be.

    Every refusal below writes a ledger entry and changes nothing else. A
    settlement that does not add up is a thing an operator needs to see, not a
    silent return.
    """
    # Idempotency is carried by durable state, not by an in-process guard, so
    # it survives restarts and concurrent deliveries.
    if link.status == "paid":
        return {
            "status": "already_recovered",
            "payment_id": link.payment_id,
            "razorpay_payment_link_id": link.razorpay_payment_link_id,
            "razorpay_payment_id": link.razorpay_payment_id,
        }

    record = db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.payment_id == link.payment_id
    ).first()

    if not record:
        return {"status": "not_found", "payment_id": link.payment_id,
                "reason": "correlation row points at a record that no longer exists"}

    def hold(reason: str) -> dict:
        log_audit(
            db, record,
            action="SETTLEMENT_MISMATCH_HELD",
            actor="system",
            details=(
                f"WHY_WE_DIDNT_ACT: settlement refused for Payment Link "
                f"{link.razorpay_payment_link_id}. {reason} "
                f"The link remains unsettled and the record is unchanged."
            ),
            cost_paise=0,
        )
        db.commit()
        return {"status": "mismatch", "payment_id": link.payment_id, "reason": reason}

    if amount != link.amount:
        return hold(
            f"Captured amount {amount} paise does not match the "
            f"{link.amount} paise this link was created for."
        )

    if currency and link.currency and currency != link.currency:
        return hold(
            f"Captured currency {currency} does not match the link currency "
            f"{link.currency}."
        )

    # Defence in depth only. Notes travel inside the webhook body, so a match
    # adds confidence while a mismatch is disqualifying - but absence proves
    # nothing, and real payloads omit them inconsistently across event types.
    claimed = (notes or {}).get("recoveros_payment_id")
    if claimed and claimed != link.payment_id:
        return hold(
            f"Webhook notes claim recoveros_payment_id={claimed}, but this link "
            f"was created for {link.payment_id}."
        )

    # The link is settled either way; the record only transitions if it is
    # still open. A record already recovered by the direct path must not get a
    # second transition.
    # Settle the link atomically. The `status == "paid"` check above is a cheap
    # early exit; this is the one that decides, because two deliveries can both
    # pass that check before either writes. Losing here means another delivery
    # is settling this link right now and this one must add nothing.
    if not idempotency.claim_link(db, link, new_payment_id):
        db.commit()
        return {
            "status": "already_recovered",
            "payment_id": link.payment_id,
            "razorpay_payment_link_id": link.razorpay_payment_link_id,
            "razorpay_payment_id": link.razorpay_payment_id,
        }

    # The record only transitions if it is still open, and transition_state now
    # says whether this caller was the one that moved it. A payment.captured
    # racing this same rupee may already have done so.
    transitioned = False
    if record.recovery_state in ("INTERVENING", "DIAGNOSED"):
        transitioned = await transition_state(
            db, record,
            to_state="RECOVERED",
            actor="system",
            details=(
                f"Payment captured via Razorpay Payment Link "
                f"{link.razorpay_payment_link_id} (new payment {new_payment_id}). "
                f"Amount: ₹{link.amount / 100:,.2f}. "
                f"Recovery channel: {record.recovery_channel}"
            ),
        )

    db.commit()

    if transitioned:
        try:
            await manager.send_metric_update({
                "event": "payment_recovered",
                "payment_id": record.payment_id,
                "amount": record.amount,
                "failure_class": record.failure_class,
            })
        except Exception:
            pass

    return {
        "status": "recovered" if transitioned else "already_recovered",
        "payment_id": record.payment_id,
        "razorpay_payment_link_id": link.razorpay_payment_link_id,
        "razorpay_payment_id": new_payment_id,
        "amount": link.amount,
    }


async def handle_payment_link_paid(db: Session, webhook_data: dict = None) -> dict:
    """
    Process a payment_link.paid webhook event.

    This is the reliable correlation path: the event names the Payment Link,
    and this system holds a row proving which record that link was created for.
    """
    link_id = _extract_payment_link_id(webhook_data)
    if not link_id:
        return {"status": "rejected", "reason": "no payment link id in payload"}

    link = db.query(RazorpayPaymentLink).filter(
        RazorpayPaymentLink.razorpay_payment_link_id == link_id
    ).first()

    if not link:
        # A link this system never created cannot recover anything. Nothing is
        # written, because there is no record to attribute an entry to.
        return {"status": "not_found", "razorpay_payment_link_id": link_id}

    entity = _payment_entity(webhook_data)
    return await _settle_via_payment_link(
        db,
        link=link,
        new_payment_id=entity.get("id"),
        amount=entity.get("amount"),
        currency=entity.get("currency"),
        notes=entity.get("notes") if isinstance(entity.get("notes"), dict) else {},
    )


async def handle_payment_captured(db: Session, payment_id: str, webhook_data: dict = None) -> dict:
    """
    Process a payment.captured webhook event.

    Direct match first, unchanged: a captured payment whose id is already a
    record settles that record. That covers the synthetic path and the case
    where the original payment itself succeeds on retry.

    Only if the direct match fails does this fall back to Payment Link
    correlation, and only when the payload genuinely contains a link id. Real
    payment.captured payloads usually do not, in which case this returns
    not_found and the dedicated payment_link.paid event does the settling.
    """
    record = db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.payment_id == payment_id
    ).first()

    if not record:
        link_id = _extract_payment_link_id(webhook_data)
        if link_id:
            link = db.query(RazorpayPaymentLink).filter(
                RazorpayPaymentLink.razorpay_payment_link_id == link_id
            ).first()
            if link:
                entity = _payment_entity(webhook_data)
                return await _settle_via_payment_link(
                    db,
                    link=link,
                    new_payment_id=payment_id,
                    amount=entity.get("amount"),
                    currency=entity.get("currency"),
                    notes=entity.get("notes") if isinstance(entity.get("notes"), dict) else {},
                )
        return {"status": "not_found", "payment_id": payment_id}

    if record.recovery_state == "RECOVERED":
        return {"status": "already_recovered", "payment_id": payment_id}

    if record.recovery_state in ("INTERVENING", "DIAGNOSED"):
        # Exactly one of a duplicate delivery, a concurrent payment_link.paid,
        # or this call transitions the record. The others report what actually
        # happened rather than claiming the recovery as their own.
        if not await transition_state(
            db, record,
            to_state="RECOVERED",
            actor="system",
            details=f"Payment captured via Razorpay webhook. "
                    f"Amount: ₹{record.amount / 100:,.2f}. "
                    f"Recovery channel: {record.recovery_channel}",
        ):
            return {"status": "already_recovered", "payment_id": payment_id}

        # Broadcast metric update
        try:
            await manager.send_metric_update({
                "event": "payment_recovered",
                "payment_id": payment_id,
                "amount": record.amount,
                "failure_class": record.failure_class,
            })
        except Exception:
            pass

        return {
            "status": "recovered",
            "payment_id": payment_id,
            "amount": record.amount,
            "failure_class": record.failure_class,
        }

    return {
        "status": "invalid_state",
        "payment_id": payment_id,
        "current_state": record.recovery_state,
    }


async def handle_invoice_paid(db: Session, invoice_id: str, webhook_data: dict = None) -> dict:
    """
    Process an invoice.paid webhook event for B2B records.
    """
    record = db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.invoice_id == invoice_id
    ).first()

    if not record:
        return {"status": "not_found", "invoice_id": invoice_id}

    if record.recovery_state in ("INTERVENING", "DIAGNOSED"):
        if not await transition_state(
            db, record,
            to_state="RECOVERED",
            actor="system",
            details=f"Invoice {invoice_id} paid. B2B receivable recovered.",
        ):
            return {"status": "already_recovered", "invoice_id": invoice_id}
        return {"status": "recovered", "invoice_id": invoice_id}

    if record.recovery_state == "RECOVERED":
        return {"status": "already_recovered", "invoice_id": invoice_id}

    return {"status": "invalid_state", "invoice_id": invoice_id}


async def check_settlement_timeouts(db: Session) -> list:
    """
    Background task: check all INTERVENING records older than SETTLEMENT_TIMEOUT_MINUTES.
    Transitions timed-out records to FAILED_STOPPED.
    """
    timeout_threshold = datetime.now(timezone.utc) - timedelta(minutes=SETTLEMENT_TIMEOUT_MINUTES)

    stale_records = db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.recovery_state == "INTERVENING",
        PaymentFailureRecord.updated_at < timeout_threshold,
    ).all()

    timed_out = []
    for record in stale_records:
        await transition_state(
            db, record,
            to_state="FAILED_STOPPED",
            actor="system",
            details=f"Settlement timeout: No payment.captured webhook received within "
                    f"{SETTLEMENT_TIMEOUT_MINUTES} minutes. Record auto-closed.",
        )
        timed_out.append(record.payment_id)

    return timed_out
