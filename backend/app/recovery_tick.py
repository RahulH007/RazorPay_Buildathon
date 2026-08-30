"""
RecoverOS Recovery Tick

The loop the live path never had.

event_adapter ingests a signed payment.failed, classifies it, and calls
execute_recovery exactly once. The simulator, by contrast, walks the escalation
ladder in a while loop, re-consulting policy before every rung - which is what
makes MAX_RETRIES reachable and the cost ceiling binding. A single-shot design
can never reach a cap of three, and the live path was exactly that: in this
project's own Test Mode database no live record has ever made a second attempt,
and three sat in INTERVENING for days behind Payment Links that expired thirty
minutes after they were created.

This module supplies the missing half. It adds no decision logic of any kind.
It decides only *which records are due*, then hands each one to the existing
chain - policy decides, the safety guard authorises, the executor acts - and
records what came back. Every rung, every refusal, every state transition is
produced by code that already existed and is already tested.

Why a tick rather than a background thread
------------------------------------------
A thread would make the system's behaviour depend on wall-clock timing inside
the process, which is precisely the property that makes a batch run
irreproducible. `now` is a parameter here, so a test can place a record at
23:30 IST and watch quiet hours defer it. Drive it from cron, from the API, or
from the CLI; the function does not care, and nothing runs unless something
asks.

Two rules earn their place
--------------------------
Rule 3 (an unpaid link holds the record open) is a correctness constraint, not
politeness. settlement._settle_via_payment_link only transitions a record out
of INTERVENING or DIAGNOSED, so closing a record whose link can still be paid
would mean a late payment marks the link paid and the recovery is lost
outright. A record may only close once every link it created is unpayable.

Rule 2 measures the last *activity*, not the last attempt. A record policy
refuses - a quiet-hours deferral, a promise to pay - produces a ledger entry
but no attempt, so keying on attempts alone would re-poll it on every pass and
append a refusal each time. The ledger is append-only and this is meant to run
on a schedule, so "touched recently" is the honest question.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import SETTLEMENT_TIMEOUT_MINUTES
from app.guardrails import ATTEMPT_ACTIONS
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.razorpay_client import LIVE_SOURCE
from app.recovery_actions import PAYMENT_LINK_EXPIRY_MINUTES, execute_recovery
from app.safety_guard import HELD_FOR_REVIEW_ACTION

# How long to leave a record alone after touching it. One settlement window:
# the same interval the system already waits before considering a payment
# unlikely to arrive, reused rather than introducing a second timeout nobody
# can relate to the first.
FOLLOW_UP_AFTER_MINUTES = SETTLEMENT_TIMEOUT_MINUTES

# States a record can still be advanced from. Identical to the safety guard's
# ACTIONABLE_STATES, and deliberately so - a record the guard would refuse on
# state grounds should never have been selected.
OPEN_STATES = ("DIAGNOSED", "INTERVENING")

# A refusal is activity: it means policy has already looked at this record
# recently and said not yet.
REFUSAL_PREFIX = "POLICY_DECLINED_"
GUARD_BLOCKED_ACTION = "SAFETY_GUARD_BLOCKED"


class SkipReason:
    """Why a record was passed over. Reported, never ledgered."""

    HELD_FOR_REVIEW = "HELD_FOR_REVIEW"
    ATTEMPT_TOO_RECENT = "ATTEMPT_TOO_RECENT"
    LINK_STILL_PAYABLE = "LINK_STILL_PAYABLE"


def _as_utc(moment: Optional[datetime]) -> Optional[datetime]:
    """
    Treat a naive datetime as UTC.

    SQLite stores DateTime columns without an offset, so a value written as
    timezone-aware reads back naive. Comparing it to an aware `now` raises;
    assuming UTC is correct here because every writer in this codebase uses
    datetime.now(timezone.utc).
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def _last_activity_us(db: Session, record: PaymentFailureRecord) -> Optional[int]:
    """
    When this record was last acted on or refused, in epoch microseconds.

    None means nothing has ever happened to it, which makes it due now - a
    record deferred at ingestion has no attempt to wait behind.
    """
    entry = (
        db.query(AuditTrailEntry)
        .filter(
            AuditTrailEntry.payment_id == record.payment_id,
            or_(
                AuditTrailEntry.action.in_(ATTEMPT_ACTIONS),
                AuditTrailEntry.action.like(f"{REFUSAL_PREFIX}%"),
                AuditTrailEntry.action == GUARD_BLOCKED_ACTION,
            ),
        )
        .order_by(AuditTrailEntry.sequence_no.desc())
        .first()
    )
    return None if entry is None else entry.timestamp_us


def _is_held_for_review(db: Session, record: PaymentFailureRecord) -> bool:
    return (
        db.query(AuditTrailEntry)
        .filter(
            AuditTrailEntry.payment_id == record.payment_id,
            AuditTrailEntry.action == HELD_FOR_REVIEW_ACTION,
        )
        .first()
        is not None
    )


def _payable_link(
    db: Session,
    record: PaymentFailureRecord,
    now: datetime,
) -> Optional[RazorpayPaymentLink]:
    """
    An unsettled Payment Link this system created that a customer could still
    pay, or None.

    Expiry is derived from created_at rather than stored, because that is how
    the link was built: recovery_actions stamps expire_by at
    PAYMENT_LINK_EXPIRY_MINUTES ahead of creation.
    """
    links = (
        db.query(RazorpayPaymentLink)
        .filter(
            RazorpayPaymentLink.payment_id == record.payment_id,
            RazorpayPaymentLink.status != "paid",
        )
        .all()
    )

    for link in links:
        created = _as_utc(link.created_at)
        if created is None:
            # A link with no creation stamp is not provably expired, and the
            # cost of guessing wrong is a lost recovery. Treat it as live.
            return link
        if created + timedelta(minutes=PAYMENT_LINK_EXPIRY_MINUTES) > now:
            return link

    return None


def open_live_records(db: Session) -> list[PaymentFailureRecord]:
    """Every live record that automation could still act on."""
    return (
        db.query(PaymentFailureRecord)
        .filter(
            PaymentFailureRecord.source == LIVE_SOURCE,
            PaymentFailureRecord.recovery_state.in_(OPEN_STATES),
        )
        .order_by(PaymentFailureRecord.created_at)
        .all()
    )


def select_due(
    db: Session,
    now: datetime,
) -> tuple[list[PaymentFailureRecord], list[dict]]:
    """
    Split the open live records into those due for a step and those not.

    Pure: reads only. This is the whole of the tick's own judgement, which is
    why dry_run can be an honest preview rather than a second code path.
    """
    due: list[PaymentFailureRecord] = []
    skipped: list[dict] = []

    for record in open_live_records(db):
        if _is_held_for_review(db, record):
            skipped.append({
                "payment_id": record.payment_id,
                "reason": SkipReason.HELD_FOR_REVIEW,
                "detail": "A person has been asked to look at this record; "
                          "automation must not overtake that request.",
            })
            continue

        link = _payable_link(db, record, now)
        if link is not None:
            skipped.append({
                "payment_id": record.payment_id,
                "reason": SkipReason.LINK_STILL_PAYABLE,
                "detail": (
                    f"Payment Link {link.razorpay_payment_link_id} is unsettled "
                    f"and has not expired. The customer can still pay it, and "
                    f"closing this record would lose a late payment."
                ),
            })
            continue

        last_us = _last_activity_us(db, record)
        if last_us is not None:
            waited = now - datetime.fromtimestamp(last_us / 1_000_000, tz=timezone.utc)
            if waited < timedelta(minutes=FOLLOW_UP_AFTER_MINUTES):
                minutes = int(waited.total_seconds() // 60)
                skipped.append({
                    "payment_id": record.payment_id,
                    "reason": SkipReason.ATTEMPT_TOO_RECENT,
                    "detail": (
                        f"Last touched {minutes} minute(s) ago, inside the "
                        f"{FOLLOW_UP_AFTER_MINUTES}-minute follow-up window."
                    ),
                })
                continue

        due.append(record)

    return due, skipped


async def advance_open_recoveries(
    db: Session,
    now: Optional[datetime] = None,
    dry_run: bool = False,
) -> dict:
    """
    Advance every live recovery that is due for its next step.

    With dry_run=True this writes nothing, calls nothing external, and returns
    the identical selection a real tick would act on - so the preview and the
    action cannot disagree about what is due.

    One record raising does not abort the pass. A tick is a batch job, and a
    single Razorpay timeout must not strand every record queued behind it; the
    failure is reported rather than swallowed.
    """
    moment = _as_utc(now) or datetime.now(timezone.utc)
    due, skipped = select_due(db, moment)

    result = {
        "now": moment.isoformat(),
        "dry_run": dry_run,
        "follow_up_after_minutes": FOLLOW_UP_AFTER_MINUTES,
        "considered": len(due) + len(skipped),
        "due": [record.payment_id for record in due],
        "skipped": skipped,
        "advanced": [],
        "failed": [],
    }

    if dry_run:
        return result

    for record in due:
        try:
            outcome = await execute_recovery(
                db, record, now=moment, source=LIVE_SOURCE
            )
        except Exception as exc:  # noqa: BLE001 - one record must not stop the pass
            db.rollback()
            result["failed"].append({
                "payment_id": record.payment_id,
                "error": f"{type(exc).__name__}: {exc}",
            })
            continue

        result["advanced"].append({
            "payment_id": record.payment_id,
            "action": outcome.get("action"),
            "reason_code": outcome.get("reason_code"),
            "guard_code": outcome.get("guard_code"),
            "channel": outcome.get("channel") or (outcome.get("decision") or {}).get("channel"),
            "recovery_state": record.recovery_state,
        })

    return result
