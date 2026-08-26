"""
RecoverOS Inbound Reply Handling

Turns a customer's message into a deterministic consequence.

The model reads the message; it never decides what happens next. The mapping
from intent to consequence lives in this file as a plain dispatch, so a
reviewer can read what a given reading of a message will cause without
inspecting a prompt.

The regex opt-out check runs alongside the model and its result is OR-ed in.
That asymmetry is deliberate: the model can only ADD suppression, never remove
it. If Gemini reads "band karo" as an agreement to pay, the contact is still
suppressed.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import CONFIDENCE_THRESHOLD
from app.consent import record_opt_out
from app.guardrails import check_opt_out
from app.llm_agent import parse_customer_reply
from app.models import PaymentFailureRecord
from app.state_machine import log_audit

WILL_PAY_GRACE_HOURS = 24


async def handle_reply(
    db: Session,
    record: PaymentFailureRecord,
    message: str,
    now: Optional[datetime] = None,
) -> dict:
    """Parse an inbound customer message and apply its consequence."""
    parsed, metadata = await parse_customer_reply(record, message)
    regex_opt_out = check_opt_out(message)

    log_audit(
        db, record,
        action="CUSTOMER_REPLY_PARSED",
        actor="llm_agent",
        details=(
            f"Reply read as '{parsed.intent}' "
            f"(confidence {parsed.confidence:.2f}, sentiment {parsed.sentiment}). "
            f"Model reasoning: {parsed.reasoning}"
        ),
        llm_metadata=metadata,
    )

    # Suppression first, and independent of confidence. A missed opt-out is the
    # one error in this system with a regulator attached to it.
    if regex_opt_out or parsed.intent == "opt_out":
        source = "keyword_match" if regex_opt_out else "llm_intent"
        record_opt_out(
            db,
            phone=record.customer_phone,
            source=f"whatsapp_reply:{source}",
            payment_id=record.payment_id,
            channel="all",
            batch_id=record.batch_id,
        )
        db.commit()
        return _result(parsed, "suppressed", regex_opt_out)

    if parsed.confidence < CONFIDENCE_THRESHOLD:
        log_audit(
            db, record,
            action="ESCALATED_TO_HUMAN",
            actor="llm_agent",
            details=(
                f"Reply confidence {parsed.confidence:.2f} below threshold "
                f"{CONFIDENCE_THRESHOLD}. No automated action taken on the "
                f"strength of an uncertain reading."
            ),
            llm_metadata=metadata,
        )
        db.commit()
        return _result(parsed, "escalated_to_human", regex_opt_out)

    if parsed.intent == "dispute":
        from app.recovery_actions import queue_for_human

        await queue_for_human(db, record)
        db.commit()
        return _result(parsed, "human_queue", regex_opt_out)

    if parsed.intent in ("request_delay", "will_pay"):
        promised = _resolve_promise_date(parsed.extracted_date, parsed.intent, now)
        record.promise_to_pay_at = promised
        log_audit(
            db, record,
            action="PROMISE_TO_PAY_RECORDED",
            actor="llm_agent",
            details=(
                f"Customer indicated payment by {promised.date().isoformat()}. "
                f"Further attempts deferred until then."
            ),
            llm_metadata=metadata,
        )
        db.commit()
        return _result(parsed, "deferred", regex_opt_out)

    db.commit()
    return _result(parsed, "none", regex_opt_out)


def _result(parsed, action_taken: str, regex_opt_out: bool) -> dict:
    return {
        "intent": parsed.intent,
        "confidence": parsed.confidence,
        "action_taken": action_taken,
        "regex_opt_out": regex_opt_out,
    }


def _resolve_promise_date(
    extracted_date: Optional[str],
    intent: str,
    now: Optional[datetime] = None,
) -> datetime:
    """
    Turn the model's date into a deferral point.

    An unparseable or absent date falls back to the grace window rather than to
    'act immediately' - the customer said something about paying, and the safe
    reading of an ambiguous promise is to wait.
    """
    moment = now or datetime.now(timezone.utc)

    if intent == "will_pay" and not extracted_date:
        return moment + timedelta(hours=WILL_PAY_GRACE_HOURS)

    if extracted_date:
        try:
            parsed = datetime.strptime(extracted_date, "%Y-%m-%d")
            return parsed.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    return moment + timedelta(hours=WILL_PAY_GRACE_HOURS)
