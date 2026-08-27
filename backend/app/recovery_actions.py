"""
RecoverOS Recovery Actions
Channel-specific recovery actions: silent retry, WhatsApp link, mandate resequence,
voice recovery, and hard decline logging.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import inspect
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models import PaymentFailureRecord, RazorpayPaymentLink
from app.schemas import FailureClass
from app.state_machine import transition_state, log_audit
from app.consent import is_suppressed
from app.llm_agent import generate_whatsapp_message
from app.policy import ReasonCode, decide_next_action
from app.config import (
    CHANNEL_COSTS_PAISE, RECOVERY_CHANNELS, DEMO_MODE,
    RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET,
    PAYMENT_LINK_CALLBACK_URL as _CONFIGURED_CALLBACK_URL,
)
from app import razorpay_client


# Razorpay validates that expire_by is at least 15 minutes in the future. The
# previous value was exactly 15, so any network or API latency between building
# the payload and Razorpay evaluating it could push the stamp under the limit
# and fail with "timestamp must be atleast 15 minutes in future". 30 minutes
# leaves a margin that latency cannot erase.
PAYMENT_LINK_EXPIRY_MINUTES = 30

# Where Razorpay returns the payer after a successful link payment. Sourced
# from config (PUBLIC_BASE_URL) rather than hardcoded: "localhost" resolves to
# the payer's own device, not to this service.
PAYMENT_LINK_CALLBACK_URL = _CONFIGURED_CALLBACK_URL


def payment_link_expiry_epoch(now=None) -> int:
    """Unix seconds for the link's expiry, PAYMENT_LINK_EXPIRY_MINUTES ahead."""
    moment = now or datetime.now(timezone.utc)
    return int((moment + timedelta(minutes=PAYMENT_LINK_EXPIRY_MINUTES)).timestamp())


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


def _loopback_callback_blocked(db: Session, record: PaymentFailureRecord, callback):
    """
    Refuse a live Payment Link whose callback nobody outside this machine can
    reach. Returns a result dict when blocked, or None when it may proceed.

    Shaped like _consent_blocked on purpose: both are refusals that happen
    inside the action rather than at the policy boundary, and both must leave
    the ledger explaining a silence a reviewer would otherwise have to guess at.
    """
    if not razorpay_client.callback_is_loopback(callback):
        return None

    log_audit(
        db, record,
        action="LIVE_LINK_BLOCKED_LOOPBACK_CALLBACK",
        actor="system",
        details=(
            f"WHY_WE_DIDNT_ACT: refused to create a live Razorpay Payment Link "
            f"because callback_url={callback!r} names a loopback host. A payer "
            f"redirected there lands on their own device, not on this service, "
            f"so the link would look valid and strand whoever paid it. No link "
            f"was created, no message was sent and nothing was spent. Set "
            f"PUBLIC_BASE_URL to a publicly reachable host and retry."
        ),
        cost_paise=0,
    )

    return {
        "action": "blocked",
        "reason": "loopback_callback_url",
        "callback_url": callback,
        "payment_link_created": False,
        "customer_contacted": False,
    }


# --- Action Implementations ---

async def silent_retry(
    db: Session,
    record: PaymentFailureRecord,
    source: str = razorpay_client.SYNTHETIC_SOURCE,
) -> dict:
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

    # Routed through the same gate as Payment Link creation. This previously
    # built a client on `if not DEMO_MODE` alone, which meant a synthetic
    # record could call Razorpay the moment demo mode was turned off - the
    # exact hole the source gate exists to close.
    if razorpay_client.is_configured(source):
        try:
            client = razorpay_client.get_client(source)
            result["downtimes"] = client.utility.fetch_payment_downtimes()
        except Exception as e:
            result["downtime_check_error"] = f"{type(e).__name__}: {e}"

    log_audit(
        db, record,
        action="RETRY_SILENT_ATTEMPT",
        actor="system",
        details=f"Silent retry attempt for {record.error_reason}. Downtime resolved: {result.get('downtime_resolved', True)}",
        cost_paise=CHANNEL_COSTS_PAISE["TRANSIENT_TECHNICAL"],
    )

    return result


async def send_whatsapp_link(
    db: Session,
    record: PaymentFailureRecord,
    source: str = razorpay_client.SYNTHETIC_SOURCE,
) -> dict:
    """
    Auth/Friction: Generate a Razorpay Payment Link and send via WhatsApp.

    `source` defaults to synthetic so every existing caller keeps working and
    stays off the network. Only a record ingested from a signed Razorpay
    webhook carries "razorpay_webhook", and only that value opens the live path.
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
        "expire_by": payment_link_expiry_epoch(),
        "callback_url": PAYMENT_LINK_CALLBACK_URL,
        # Correlation metadata, not a trust anchor. It travels back inside the
        # webhook body, so it is used to locate our own RazorpayPaymentLink row
        # and never to decide on its own which record a payment settles.
        "notes": {"recoveros_payment_id": record.payment_id},
    }

    result = {
        "action": "whatsapp_link",
        "payment_link_created": True,
        "link_url": f"https://rzp.io/i/demo_{record.payment_id[-8:]}",
        "expiry_minutes": PAYMENT_LINK_EXPIRY_MINUTES,
    }

    # The live path is gated on source as well as DEMO_MODE, so the synthetic
    # batch cannot reach the network even with real credentials loaded.
    live_link = None
    if razorpay_client.is_configured(source):
        # Fail closed before the API call, not after it. A live link whose
        # callback is loopback strands the payer on their own device, and once
        # Razorpay has created it the damage is a real URL that can be sent to a
        # real person. Refusing here means no link exists to send, so the action
        # stops rather than falling back to a demo URL a live customer would be
        # given as if it were genuine.
        blocked = _loopback_callback_blocked(
            db, record, payment_link_data.get("callback_url")
        )
        if blocked:
            return blocked

        try:
            live_link = razorpay_client.create_payment_link(source, payment_link_data)
            result["link_url"] = live_link.get("short_url", result["link_url"])
            result["link_id"] = live_link.get("id")
        except Exception as e:
            # A failed creation must leave nothing durable behind claiming a
            # link exists, so live_link stays None and no correlation row is
            # written below. The fallback demo URL is kept so the record still
            # progresses, and the failure is surfaced rather than swallowed.
            live_link = None
            result["payment_link_created"] = False
            result["error"] = f"{type(e).__name__}: {e}"
            print(f"[ERROR] Razorpay Payment Link creation failed for "
                  f"{record.payment_id}: {type(e).__name__}: {e}")

    message_text, llm_metadata, rejection = await generate_whatsapp_message(
        record, result["link_url"]
    )
    result["message"] = message_text

    if rejection:
        # A rejected message is ledgered rather than swallowed: the guard is
        # only worth having if a reviewer can see it fire.
        log_audit(
            db, record,
            action="LLM_OUTPUT_REJECTED",
            actor="policy_engine",
            details=f"Generated message rejected, template sent instead. "
                    f"Reason: {rejection}",
            llm_metadata=llm_metadata or None,
        )

    action_entry = log_audit(
        db, record,
        action="WHATSAPP_LINK_SENT",
        actor="system",
        details=f"WhatsApp payment link sent to {record.customer_phone}: "
                f"{result['link_url']} | message: {message_text}",
        cost_paise=CHANNEL_COSTS_PAISE["AUTH_FRICTION"],
        llm_metadata=llm_metadata or None,
    )

    # Correlation is persisted only for a link that Razorpay actually created.
    # A demo placeholder URL gets no row: a row here asserts that a real link
    # with this id exists at Razorpay, and settlement will trust it.
    #
    # Ordering matters. The ledger entry is written first so its entry_hash can
    # be the recovery_action_id, which ties the link to the exact, tamper-
    # evident record of the action that produced it.
    if live_link and live_link.get("id"):
        db.add(RazorpayPaymentLink(
            payment_id=record.payment_id,
            recovery_action_id=action_entry.entry_hash,
            razorpay_payment_link_id=live_link["id"],
            razorpay_payment_id=None,  # unknown until the link is paid
            status="created",
            amount=record.amount,
            currency=record.currency or "INR",
        ))
        db.commit()
        result["correlation_recorded"] = True

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
    source: str = None,
) -> dict:
    """
    Run one policy-approved recovery step against this record.

    Performs a single attempt rather than the whole ladder; the caller loops.
    That keeps the decision (policy), the action (here), and the outcome
    (the simulator or a real webhook) separable, and means each attempt gets
    a fresh guard evaluation instead of one check at the start.

    `source` decides whether an action may reach the live Razorpay API. It
    defaults to the record's own source, so a caller that does not pass it
    cannot accidentally upgrade a synthetic record to the live path - the
    record itself carries where it came from.
    """
    source = source or getattr(record, "source", None) or razorpay_client.SYNTHETIC_SOURCE
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

        # Three refusals leave the record open rather than closing it:
        #   QUIET_HOURS_DEFERRED   - the call still has to be placed later
        #   HOLDOUT_CONTROL        - the control arm is observed, not abandoned
        #   PROMISE_TO_PAY_PENDING - the customer asked for time, not to stop
        terminal = decision.reason_code not in (
            ReasonCode.QUIET_HOURS_DEFERRED,
            ReasonCode.HOLDOUT_CONTROL,
            ReasonCode.PROMISE_TO_PAY_PENDING,
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

    # Only the actions that can reach Razorpay accept a source; the rest keep
    # their existing two-argument signature.
    if "source" in inspect.signature(action_fn).parameters:
        result = await action_fn(db, record, source=source)
    else:
        result = await action_fn(db, record)
    result["payment_id"] = record.payment_id
    result["failure_class"] = record.failure_class
    result["decision"] = decision.to_dict()

    return result
