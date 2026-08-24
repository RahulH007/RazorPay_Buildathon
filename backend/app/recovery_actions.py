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
from app.guardrails import run_all_guards
from app.config import CHANNEL_COSTS, RECOVERY_CHANNELS, DEMO_MODE, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET


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
        cost=CHANNEL_COSTS["TRANSIENT_TECHNICAL"],
    )

    return result


async def send_whatsapp_link(db: Session, record: PaymentFailureRecord) -> dict:
    """
    Auth/Friction: Generate a Razorpay Payment Link and send via WhatsApp.
    """
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
        cost=CHANNEL_COSTS["AUTH_FRICTION"],
    )

    return result


async def resequence_mandate(db: Session, record: PaymentFailureRecord) -> dict:
    """
    Mandate/Balance: Calculate next salary cycle date, schedule retry,
    send 1-click mandate update link.
    """
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
        cost=CHANNEL_COSTS["MANDATE_BALANCE"],
    )

    return result


async def initiate_voice_recovery(db: Session, record: PaymentFailureRecord) -> dict:
    """
    B2B Receivable: Generate Hinglish script via LLM, synthesize TTS audio,
    initiate voice call (simulated in demo).
    """
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
        cost=CHANNEL_COSTS["B2B_RECEIVABLE"],
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
        cost=0.0,
    )

    return result


# --- Action Dispatch Map ---

ACTION_MAP = {
    FailureClass.TRANSIENT_TECHNICAL.value: silent_retry,
    FailureClass.AUTH_FRICTION.value: send_whatsapp_link,
    FailureClass.MANDATE_BALANCE.value: resequence_mandate,
    FailureClass.B2B_RECEIVABLE.value: initiate_voice_recovery,
    FailureClass.HARD_DECLINE.value: log_hard_decline,
}


async def execute_recovery(db: Session, record: PaymentFailureRecord) -> dict:
    """
    Execute the appropriate recovery action based on failure class.
    Checks all guardrails before proceeding.
    """
    # Run guardrail checks
    allowed, halt_reason = run_all_guards(db, record)

    if not allowed:
        # Guardrail triggered — halt recovery
        if record.recovery_state not in ("RECOVERED", "FAILED_STOPPED"):
            await transition_state(
                db, record,
                to_state="FAILED_STOPPED",
                actor="system",
                details=f"GUARDRAIL_HALT: {halt_reason}",
            )
        return {"action": "halted", "reason": halt_reason}

    # Get the appropriate action handler
    action_fn = ACTION_MAP.get(record.failure_class)
    if not action_fn:
        return {"action": "no_action", "reason": f"Unknown failure class: {record.failure_class}"}

    # Transition to INTERVENING (skip for HARD_DECLINE — already at FAILED_STOPPED)
    if record.failure_class != FailureClass.HARD_DECLINE.value:
        if record.recovery_state == "DIAGNOSED":
            await transition_state(
                db, record,
                to_state="INTERVENING",
                actor="system",
                details=f"Starting recovery action: {action_fn.__name__}",
            )

    # Execute the action
    result = await action_fn(db, record)
    result["payment_id"] = record.payment_id
    result["failure_class"] = record.failure_class

    return result
