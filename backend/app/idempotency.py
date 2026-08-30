"""
RecoverOS Idempotency
Exactly-once guarantees for duplicate deliveries and concurrent workers.

Everything this system did to stay idempotent used to be read-then-write:

    if record.recovery_state in ("INTERVENING", "DIAGNOSED"): transition(...)
    if link.status == "paid": return already_recovered
    if existing: return duplicate
    attempts = count_attempts(db, record)      # then decide, then act

Each is correct in a single thread and none of them is atomic. Two callers
holding their own sessions both read the open state, both pass the check, and
both act. That is not a rare interleaving: Razorpay retries delivery on any
non-2xx and on a timeout, fires payment.captured and payment_link.paid for the
same rupee, and the recovery tick is an endpoint anybody can call twice.

The two costs are different in kind, and both matter:

    a second RECOVERED transition puts a false claim on an append-only chain
    whose entire purpose is to be believed

    a second recovery action sends a real WhatsApp message to a real person who
    has already been messaged, and creates a second Payment Link at Razorpay

Both are closed here with the same technique the ledger already uses: let the
database decide, through a constraint or a conditional write, rather than
letting the application decide from something it read a moment ago.

Three primitives
----------------
claim_state       one conditional UPDATE against the state the caller believes
                  it is leaving. Exactly one concurrent caller can match.

claim_link        the same, for a Payment Link's settled flag.

claim_attempt     an INSERT against a UNIQUE index over
                  (payment_id, batch_key, attempt_number). The insert IS the
                  lock: the loser gets an IntegrityError, not a second send.

Why a table for the attempt claim
---------------------------------
The other two ride on columns that already exist, because both are compare-and-
set on a value that changes as a result of the operation. An attempt is not:
the third WhatsApp message leaves the record in the same state as the second,
so there is no existing column whose value distinguishes "about to make attempt
2" from "about to make attempt 2 again". A counter column would have to be
written before the action and rolled back after a failure, which is the same
read-then-write problem one level down. A UNIQUE insert is atomic across
processes, survives a restart, and is the single technique in this codebase
already trusted for exactly this - the ledger's chain cannot fork because two
rows may not share a prev_hash.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import PaymentFailureRecord, RazorpayPaymentLink, RecoveryAttemptClaim

# Stands in for a record with no batch.
#
# SQL treats NULLs as distinct, so a UNIQUE index over a nullable batch_id would
# happily accept (pay_x, NULL, 0) twice - and every live webhook record carries
# no batch at all. The sentinel is therefore not a tidiness choice: without it
# the claim would protect the demo and leave the live path wide open.
NO_BATCH = ""

# Returned inside the executor's result when a duplicate was suppressed.
DUPLICATE_REASON_CODE = "DUPLICATE_SUPPRESSED"


def batch_key(record: PaymentFailureRecord) -> str:
    """The batch half of a claim key, never NULL."""
    return record.batch_id or NO_BATCH


def claim_state(
    db: Session,
    record: PaymentFailureRecord,
    from_states: Iterable[str],
    to_state: str,
) -> bool:
    """
    Move this record to `to_state`, atomically, if it is still in one of
    `from_states`.

    True means this caller made the transition and nobody else did. False means
    someone else got there first and this caller must not report the outcome as
    its own - answering "recovered" for a transition another delivery made is
    how a duplicate webhook becomes a duplicate figure downstream.

    One statement, so the check and the write cannot be separated by another
    session. The caller's in-memory record is refreshed on success, because
    after this it is authoritative rather than the copy the caller loaded.
    """
    states = list(from_states)
    result = db.execute(
        update(PaymentFailureRecord)
        .where(PaymentFailureRecord.payment_id == record.payment_id,
               PaymentFailureRecord.recovery_state.in_(states))
        .values(recovery_state=to_state,
                updated_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        return False

    # The row is ours. Bring the caller's copy in line so everything after this
    # - the ledger entry, the websocket broadcast, the returned payload - is
    # describing the record as it now is.
    db.expire(record)
    return True


def claim_link(
    db: Session,
    link: RazorpayPaymentLink,
    razorpay_payment_id: Optional[str],
) -> bool:
    """
    Mark a Payment Link settled, atomically, if it is not settled already.

    The link row is the trust anchor for correlation, so it is also the right
    place to decide which delivery of payment_link.paid is the real one.
    """
    result = db.execute(
        update(RazorpayPaymentLink)
        .where(RazorpayPaymentLink.id == link.id,
               RazorpayPaymentLink.status != "paid")
        .values(status="paid",
                razorpay_payment_id=razorpay_payment_id,
                updated_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )

    if result.rowcount != 1:
        return False

    db.expire(link)
    return True


def claim_attempt(
    db: Session,
    record: PaymentFailureRecord,
    attempt_number: int,
) -> bool:
    """
    Reserve the right to make this specific attempt on this specific record.

    True for exactly one caller per (payment, batch, attempt number), enforced
    by the database rather than by anything read beforehand. False means
    another worker is making - or has already made - this exact attempt, and
    this caller must do nothing at all.

    Keyed on the attempt number so suppression is exactly-once rather than
    once-ever: the ladder still escalates, because attempt 1 is a different
    claim from attempt 0. Keyed on the batch as well because the ledger is
    append-only and the simulator re-runs the same payment ids under a new
    batch id - a claim ignoring that would make every record in the second run
    look already-claimed and stop the demo dead.
    """
    claim = RecoveryAttemptClaim(
        payment_id=record.payment_id,
        batch_key=batch_key(record),
        attempt_number=attempt_number,
    )
    db.add(claim)
    try:
        db.commit()
    except IntegrityError:
        # The loser of the race. Roll back to a clean session and say so; there
        # is nothing to repair, because the winner is doing the work.
        db.rollback()
        return False
    return True


def release_attempt(
    db: Session,
    record: PaymentFailureRecord,
    attempt_number: int,
) -> None:
    """
    Give the claim back.

    Called only when an attempt failed *before* anything reached the customer,
    so that the next tick can try the same rung again. A claim must not become
    a tombstone: a Razorpay timeout on rung one should cost a retry, not the
    rung.

    The converse is the expensive case and is decided by the caller, not here.
    Once a send has been recorded on the ledger the customer has been
    contacted, and the claim is kept even though the attempt raised afterwards
    - releasing it would send them a second copy of the same message.
    """
    db.query(RecoveryAttemptClaim).filter(
        RecoveryAttemptClaim.payment_id == record.payment_id,
        RecoveryAttemptClaim.batch_key == batch_key(record),
        RecoveryAttemptClaim.attempt_number == attempt_number,
    ).delete(synchronize_session=False)
    db.commit()
