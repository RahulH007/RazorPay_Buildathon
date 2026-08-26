"""
Consent registry tests.

The load-bearing test is cross-payment suppression: opting out on one payment
must silence the contact's *other* payments. A per-payment flag passes every
other test in this file and still fails that one, which is exactly why the
original implementation looked correct.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from datetime import datetime, timezone

import pytest

from app import consent, ledger
from app.config import IST
from app.models import ConsentRecord


# --- Phone normalization ----------------------------------------------------


def test_indian_number_formats_resolve_to_one_identity():
    """Suppression leaks if +91, 91, 0 and bare forms hash differently."""
    variants = [
        "+919876543210",
        "919876543210",
        "09876543210",
        "9876543210",
        "+91 98765 43210",
        "+91-98765-43210",
    ]
    hashes = {consent.contact_hash(v) for v in variants}
    assert len(hashes) == 1, f"Same number produced {len(hashes)} identities"


def test_different_numbers_do_not_collide():
    assert consent.contact_hash("+919876543210") != consent.contact_hash("+919876543211")


def test_registry_stores_no_raw_phone_number(db_session, payment_record):
    """The registry answers a yes/no question; it has no reason to hold a PII identifier."""
    phone = "+919876543210"
    record = payment_record(customer_phone=phone)
    db_session.add(record)
    db_session.commit()

    consent.record_opt_out(db_session, phone, "api", record.payment_id)

    stored = db_session.query(ConsentRecord).one()
    assert "9876543210" not in stored.contact_hash
    assert len(stored.contact_hash) == 64


# --- Suppression ------------------------------------------------------------


def test_opt_out_suppresses_the_same_contact_on_a_different_payment(
    db_session, payment_record
):
    """
    The point of the whole module.

    Two failed payments, one customer. Opting out on the first must silence
    the second — the per-payment implementation this replaces did not.
    """
    phone = "+919876543210"
    first = payment_record(payment_id="pay_first", customer_phone=phone)
    second = payment_record(payment_id="pay_second", customer_phone=phone)
    db_session.add_all([first, second])
    db_session.commit()

    assert consent.is_suppressed(db_session, phone, "whatsapp")[0] is False

    consent.record_opt_out(db_session, phone, "dtmf_9", "pay_first")

    suppressed, reason = consent.is_suppressed(db_session, phone, "whatsapp")
    assert suppressed is True
    assert "CONSENT_WITHDRAWN" in reason
    assert "pay_first" in reason


def test_opt_out_does_not_suppress_a_different_contact(db_session, payment_record):
    opted_out = payment_record(payment_id="pay_a", customer_phone="+919876543210")
    other = payment_record(payment_id="pay_b", customer_phone="+919811111111")
    db_session.add_all([opted_out, other])
    db_session.commit()

    consent.record_opt_out(db_session, "+919876543210", "api", "pay_a")

    assert consent.is_suppressed(db_session, "+919811111111", "whatsapp")[0] is False


def test_silent_retry_is_never_gated_on_consent(db_session, payment_record):
    """A server-to-server bank retry never reaches the customer."""
    phone = "+919876543210"
    record = payment_record(customer_phone=phone)
    db_session.add(record)
    db_session.commit()

    consent.record_opt_out(db_session, phone, "api", record.payment_id)

    assert consent.is_suppressed(db_session, phone, "silent_retry")[0] is False
    assert consent.is_suppressed(db_session, phone, "whatsapp")[0] is True


def test_opt_out_is_idempotent(db_session, payment_record):
    phone = "+919876543210"
    record = payment_record(customer_phone=phone)
    db_session.add(record)
    db_session.commit()

    consent.record_opt_out(db_session, phone, "api", record.payment_id)
    consent.record_opt_out(db_session, phone, "dtmf_9", record.payment_id)

    assert db_session.query(ConsentRecord).count() == 1


def test_opt_out_writes_a_ledger_entry(db_session, payment_record):
    phone = "+919876543210"
    record = payment_record(customer_phone=phone)
    db_session.add(record)
    db_session.commit()

    consent.record_opt_out(db_session, phone, "dtmf_9", record.payment_id)

    result = ledger.verify_chain(db_session)
    assert result.valid is True
    assert result.entries_checked == 1

    from app.models import AuditTrailEntry
    entry = db_session.query(AuditTrailEntry).one()
    assert entry.action == "CONSENT_WITHDRAWN"
    assert entry.actor == "customer"
    assert "every future payment" in entry.details


# --- Quiet hours ------------------------------------------------------------


@pytest.mark.parametrize(
    "hour,expected",
    [(8, True), (9, False), (14, False), (20, False), (21, True), (23, True), (3, True)],
)
def test_quiet_hours_window(hour, expected):
    """TRAI permits promotional voice calls only between 09:00 and 21:00 IST."""
    moment = datetime(2026, 8, 25, hour, 30, tzinfo=IST)
    assert consent.in_quiet_hours(moment) is expected


def test_quiet_hours_block_voice_but_not_whatsapp(db_session, payment_record):
    """A message is asynchronous and wakes nobody; a call does."""
    phone = "+919876543210"
    record = payment_record(customer_phone=phone)
    db_session.add(record)
    db_session.commit()

    midnight = datetime(2026, 8, 25, 23, 30, tzinfo=IST)

    voice_blocked, reason = consent.is_suppressed(db_session, phone, "voice", midnight)
    assert voice_blocked is True
    assert "QUIET_HOURS_DEFERRED" in reason

    assert consent.is_suppressed(db_session, phone, "whatsapp", midnight)[0] is False


def test_quiet_hours_defer_to_next_morning():
    late = datetime(2026, 8, 25, 22, 0, tzinfo=IST)
    resume = consent.next_permitted_time(late)
    assert resume.hour == 9
    assert resume.day == 26

    early = datetime(2026, 8, 25, 3, 0, tzinfo=IST)
    resume = consent.next_permitted_time(early)
    assert resume.hour == 9
    assert resume.day == 25
