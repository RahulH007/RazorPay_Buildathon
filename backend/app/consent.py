"""
RecoverOS Consent Registry
Customer-level suppression, not per-payment.

The distinction matters. Marking one payment FAILED_STOPPED does not stop the
next failed payment from the same person being contacted next week, which is
precisely what an opt-out exists to prevent. Consent is therefore keyed on the
contact, and every outbound checks it.

Phone numbers are stored only as a SHA-256 hash. The registry never needs the
raw number — it only ever answers "is this contact suppressed?" — so it should
not hold one.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app import ledger
from app.config import (
    QUIET_HOURS_END_HOUR,
    QUIET_HOURS_START_HOUR,
    IST,
)
from app.models import ConsentRecord

# Channels that require consent before an outbound. Silent retry is absent by
# design: it is a server-to-server retry against the bank and never reaches
# the customer, so consent does not apply.
CONSENTED_CHANNELS = ("whatsapp", "voice", "sms")

# Channels subject to quiet hours. A WhatsApp message is asynchronous and does
# not wake anyone, so only voice is time-restricted.
QUIET_HOUR_CHANNELS = ("voice",)


def normalize_phone(phone: str) -> str:
    """
    Reduce a phone number to a comparable form.

    Indian numbers arrive as +919876543210, 919876543210, 09876543210 or
    9876543210. All must resolve to one identity or suppression leaks.
    """
    if not phone:
        return ""

    digits = re.sub(r"\D", "", phone)

    if len(digits) > 10 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    return digits[-10:] if len(digits) >= 10 else digits


def contact_hash(phone: str) -> str:
    """SHA-256 of the normalized number. The registry's only identifier."""
    return hashlib.sha256(normalize_phone(phone).encode("utf-8")).hexdigest()


# --- Quiet hours ------------------------------------------------------------


def in_quiet_hours(now: Optional[datetime] = None) -> bool:
    """
    True inside the window where marketing voice calls are not permitted.

    TRAI restricts promotional voice calls to 09:00-21:00 IST. The window wraps
    midnight, so the comparison is an OR rather than a range.
    """
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    return now.hour >= QUIET_HOURS_START_HOUR or now.hour < QUIET_HOURS_END_HOUR


def next_permitted_time(now: Optional[datetime] = None) -> datetime:
    """When a deferred call becomes permissible. Returns IST."""
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    if not in_quiet_hours(now):
        return now

    target = now.replace(
        hour=QUIET_HOURS_END_HOUR, minute=0, second=0, microsecond=0
    )
    if now.hour >= QUIET_HOURS_START_HOUR:
        target += timedelta(days=1)
    return target


# --- Registry ---------------------------------------------------------------


def is_suppressed(
    db: Session,
    phone: str,
    channel: str,
    now: Optional[datetime] = None,
) -> tuple[bool, Optional[str]]:
    """
    Decide whether an outbound on this channel to this contact is permitted.

    Returns (suppressed, reason). Two distinct outcomes are folded into one
    call deliberately, because both must block the send:
      * CONSENT_WITHDRAWN — permanent, the customer opted out
      * QUIET_HOURS_DEFERRED — temporary, retry after the window
    """
    if channel not in CONSENTED_CHANNELS:
        return False, None

    digest = contact_hash(phone)
    record = (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.contact_hash == digest,
            ConsentRecord.channel.in_([channel, "all"]),
            ConsentRecord.opted_out.is_(True),
        )
        .first()
    )

    if record:
        return True, (
            f"CONSENT_WITHDRAWN: contact opted out of {record.channel} "
            f"via {record.source} on {ledger.us_to_iso(record.recorded_at_us)} "
            f"(payment {record.payment_id})"
        )

    if channel in QUIET_HOUR_CHANNELS and in_quiet_hours(now):
        resume = next_permitted_time(now)
        return True, (
            f"QUIET_HOURS_DEFERRED: voice calls are not placed between "
            f"{QUIET_HOURS_START_HOUR}:00 and {QUIET_HOURS_END_HOUR}:00 IST. "
            f"Deferred to {resume.strftime('%Y-%m-%d %H:%M')} IST"
        )

    return False, None


def record_opt_out(
    db: Session,
    phone: str,
    source: str,
    payment_id: str,
    channel: str = "all",
    batch_id: Optional[str] = None,
) -> ConsentRecord:
    """
    Withdraw consent for a contact and write it to the ledger.

    Idempotent: opting out twice does not create a second row, because the
    registry answers a yes/no question and duplicates would only obscure when
    consent was first withdrawn.
    """
    digest = contact_hash(phone)

    existing = (
        db.query(ConsentRecord)
        .filter(
            ConsentRecord.contact_hash == digest,
            ConsentRecord.channel == channel,
        )
        .first()
    )

    if existing and existing.opted_out:
        return existing

    record = ConsentRecord(
        contact_hash=digest,
        channel=channel,
        opted_out=True,
        source=source,
        payment_id=payment_id,
        recorded_at_us=ledger.now_us(),
    )
    db.add(record)
    db.commit()

    ledger.append_entry(
        db,
        payment_id=payment_id,
        batch_id=batch_id,
        action="CONSENT_WITHDRAWN",
        actor="customer",
        details=(
            f"Contact opted out of '{channel}' via {source}. "
            f"Suppression applies to every future payment from this contact, "
            f"not only {payment_id}. Contact reference: {digest[:16]}..."
        ),
    )

    return record


def suppression_count(db: Session) -> int:
    """How many contacts are currently suppressed. Used by the dashboard."""
    return (
        db.query(ConsentRecord)
        .filter(ConsentRecord.opted_out.is_(True))
        .count()
    )
