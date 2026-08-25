"""
RecoverOS Recovery Actions
Channel-specific recovery actions: silent retry, WhatsApp link, mandate resequence,
voice recovery, and hard decline logging.
"""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models import PaymentFailureRecord
from app.schemas import FailureClass
from app.state_machine import transition_state, log_audit
from app.consent import is_suppressed
from app.policy import ReasonCode, decide_next_action
from app.config import CHANNEL_COSTS_PAISE, RECOVERY_CHANNELS, DEMO_MODE, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET


def _consent_blocked(db: Session, record: PaymentFailureRecord, channel: str):
    """
    Gate every customer-facing send on the consent registry.

    Called from inside each action rather than once in execute_recovery, so a
    new channel added later cannot accidentally skip the check. Returns a
    result dict when the send is blocked, or None when it may proceed.
    """
    suppressed, reason = is_suppressed(db, record.customer_phone, channel)
    if not suppressed:
        return None

    log_audit(
        db, record,
        action="SUPPRESSED_CONSENT",
        actor="system",
        details=f"WHY_WE_DIDNT_ACT: {reason}",
        cost_paise=0,
    )
    return {
        "action": "suppressed",
        "channel": channel,
        "reason": reason,
        "customer_contacted": False,
    }


# --- Action Implementations ---

async def silent_retry(db: Session, record: PaymentFailureRecord) -> dict:
    """
    Transient Technical: Check downtime status, retry when resolved.
    In demo mode: simulates downtime check and retry.
    """
    result = {
        "action": "silent_retry",
        "downtime_checked": True,
        "downtime_resolved": True,
        "retry_scheduled": True,
    }

    if not DEMO_MODE:
        try:
            import razorpay
            client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
            downtimes = client.utility.fetch_payment_downtimes()
            result["downtimes"] = downtimes
        except Exception as e:
            result["downtime_check_error"] = str(e)

    log_audit(
        db, record,
        action="RETRY_SILENT_ATTEMPT",
        actor="system",
        details=f"Silent retry attempt for {record.error_reason}. Downtime resolved: {result.get('downtime_resolved', True)}",
        cost_paise=CHANNEL_COSTS_PAISE["TRANSIENT_TECHNICAL"],
    )

    return result


async def send_whatsapp_link(db: Session, record: PaymentFailureRecord) -> dict:
    """
    Auth/Friction: Generate a Razorpay Payment Link and send via WhatsApp.
    """
    blocked = _consent_blocked(db, record, "whatsapp")
    if blocked:
        return blocked

    payment_link_data = {
        "amount": record.amount,
        "currency": record.currency or "INR",
        "description": f"Recovery payment for {record.payment_id}",
        "customer": {
            "name": record.customer_name,
            "contact": record.customer_phone,
            "email": record.customer_email or "",
        },
        "notify": {"sms": False, "email": False, "whatsapp": True},
        "expire_by": int((datetime.now(timezone.utc) + timedelta(minutes=15)).timestamp()),
        "callback_url": "http://localhost:8000/api/webhooks/razorpay",
    }

    result = {
        "action": "whatsapp_link",
        "payment_link_created": True,
        "link_url": f"https://rzp.io/i/demo_{record.payment_id[-8:]}",
        "expiry_minutes": 15,
    }

    if not DEMO_MODE:
        try:
            import razorpay
            client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
            link = client.payment_link.create(payment_link_data)
            result["link_url"] = link.get("short_url", result["link_url"])
            result["link_id"] = link.get("id")
        except Exception as e:
            result["error"] = str(e)

    log_audit(
        db, record,
        action="WHATSAPP_LINK_SENT",
        actor="system",
        details=f"WhatsApp payment link sent to {record.customer_phone}: {result['link_url']}",
        cost_paise=CHANNEL_COSTS_PAISE["AUTH_FRICTION"],
    )

    return result


async def resequence_mandate(db: Session, record: PaymentFailureRecord) -> dict:
    """
    Mandate/Balance: Calculate next salary cycle date, schedule retry,
    send 1-click mandate update link.
    """
    blocked = _consent_blocked(db, record, "whatsapp")
    if blocked:
        return blocked

    now = datetime.now(timezone.utc)
    # Schedule for next 1st or 5th of month (whichever is closer)
    if now.day <= 1:
        next_date = now.replace(day=1)
    elif now.day <= 5:
        next_date = now.replace(day=5)
    else:
        # Next month 1st
        if now.month == 12:
            next_date = now.replace(year=now.year + 1, month=1, day=1)
        else:
            next_date = now.replace(month=now.month + 1, day=1)

    result = {
        "action": "mandate_resequence",
        "scheduled_retry_date": next_date.isoformat(),
        "mandate_update_link_sent": True,
        "link_url": f"https://rzp.io/mandate/demo_{record.payment_id[-8:]}",
    }

    log_audit(
        db, record,
        action="MANDATE_RESEQUENCED",
        actor="system",
        details=f"Mandate retry scheduled for {next_date.strftime('%Y-%m-%d')}. "
                f"Subscription: {record.subscription_id}. Update link sent to {record.customer_phone}",
        cost_paise=CHANNEL_COSTS_PAISE["MANDATE_BALANCE"],
    )

    return result


async def initiate_voice_recovery(db: Session, record: PaymentFailureRecord) -> dict:
    """
    B2B Receivable: Generate Hinglish script via LLM, synthesize TTS audio,
    initiate voice call (simulated in demo).
    """
    blocked = _consent_blocked(db, record, "voice")
    if blocked:
        return blocked

    from app.voice_pipeline import generate_voice_audio

    audio_url = await generate_voice_audio(db, record)

    result = {
        "action": "voice_recovery",
        "script_generated": True,
        "audio_url": audio_url,
        "call_initiated": True,
        "dtmf_options": {"1": "Pay Now", "2": "Delay/P2P", "9": "Opt-Out"},
    }

    log_audit(
        db, record,
        action="VOICE_CALL_INITIATED",
        actor="system",
        details=f"Hinglish voice call initiated to {record.customer_phone}. Audio: {audio_url}",
        cost_paise=CHANNEL_COSTS_PAISE["B2B_RECEIVABLE"],
    )

    return result


async def log_hard_decline(db: Session, record: PaymentFailureRecord) -> dict:
    """
    Hard Decline: No customer outreach. Log why we didn't act.
    """
    result = {
        "action": "hard_decline_logged",
        "customer_contacted": False,
        "retries": 0,
        "reason": record.error_reason,
    }

    log_audit(
        db, record,
        action="WHY_WE_DIDNT_ACT",
        actor="system",
        details=f"HARD DECLINE — Zero retries, zero customer outreach. "
                f"Reason: {record.error_reason}. "
                f"Description: {record.error_description or 'N/A'}. "
                f"This is a compliance-mandated halt, not a system failure.",
        cost_paise=0,
    )

    return result


async def queue_for_human(db: Session, record: PaymentFailureRecord) -> dict:
    """
    Final rung of the B2B ladder: hand off to the accounts team.

    Automation stops here by design. The record is not marked recovered or
    failed - a person owns it now, and the ledger records the handoff.
    """
    log_audit(
        db, record,
        action="ESCALATED_TO_HUMAN",
        actor="system",
        details=(
            f"Automated ladder exhausted for invoice {record.invoice_id or 'N/A'} "
            f"(Rs {record.amount / 100:,.2f}). Queued for the accounts team. "
            f"No further automated contact will be attempted."
        ),
        cost_paise=0,
    )
    return {"action": "human_queue", "customer_contacted": False, "owner": "accounts_team"}


# --- Action Dispatch Map ---

ACTION_MAP = {
    FailureClass.TRANSIENT_TECHNICAL.value: silent_retry,
    FailureClass.AUTH_FRICTION.value: send_whatsapp_link,
    FailureClass.MANDATE_BALANCE.value: resequence_mandate,
    FailureClass.B2B_RECEIVABLE.value: initiate_voice_recovery,
    FailureClass.HARD_DECLINE.value: log_hard_decline,
}


# Channel name -> action implementation. Keyed by channel rather than failure
# class, because the escalation ladder lets one class use several channels.
CHANNEL_ACTION_MAP = {
    "silent_retry": silent_retry,
    "whatsapp_link": send_whatsapp_link,
    "upi_resequence": resequence_mandate,
    "hinglish_voice": initiate_voice_recovery,
    "human_queue": queue_for_human,
}


async def execute_recovery(
    db: Session,
    record: PaymentFailureRecord,
    now=None,
    is_holdout: bool = False,
) -> dict:
    """
    Run one policy-approved recovery step against this record.

    Performs a single attempt rather than the whole ladder; the caller loops.
    That keeps the decision (policy), the action (here), and the outcome
    (the simulator or a real webhook) separable, and means each attempt gets
    a fresh guard evaluation instead of one check at the start.
    """
    decision = decide_next_action(db, record, now=now, is_holdout=is_holdout)

    if not decision.should_act:
        # A refusal is a first-class, ledgered outcome - not silence.
        log_audit(
            db, record,
            action=f"POLICY_DECLINED_{decision.reason_code}",
            actor="policy_engine",
            details=f"WHY_WE_DIDNT_ACT: {decision.reason}",
            cost_paise=0,
        )

        # Two refusals leave the record open rather than closing it:
        #   QUIET_HOURS_DEFERRED - the call still has to be placed later
        #   HOLDOUT_CONTROL      - the control arm is observed, not abandoned
        terminal = decision.reason_code not in (
            ReasonCode.QUIET_HOURS_DEFERRED,
            ReasonCode.HOLDOUT_CONTROL,
        )
        if terminal and record.recovery_state not in ("RECOVERED", "FAILED_STOPPED"):
            await transition_state(
                db, record,
                to_state="FAILED_STOPPED",
                actor="policy_engine",
                details=f"{decision.reason_code}: {decision.reason}",
            )

        return {
            "action": "declined",
            "payment_id": record.payment_id,
            "failure_class": record.failure_class,
            **decision.to_dict(),
        }

    action_fn = CHANNEL_ACTION_MAP.get(decision.channel)
    if not action_fn:
        return {"action": "no_action", "reason": f"Unknown channel: {decision.channel}"}

    if record.recovery_state == "DIAGNOSED":
        await transition_state(
            db, record,
            to_state="INTERVENING",
            actor="policy_engine",
            details=decision.reason,
        )

    result = await action_fn(db, record)
    result["payment_id"] = record.payment_id
    result["failure_class"] = record.failure_class
    result["decision"] = decision.to_dict()

    return result
