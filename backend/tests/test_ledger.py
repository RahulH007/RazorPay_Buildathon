"""
Ledger tests.

The golden-fixture test is the important one: it pins the canonical preimage
byte-for-byte. Any change to field order, encoders, or PREIMAGE_VERSION fails
here loudly, rather than silently invalidating every hash already written.
"""

import hashlib
import sqlite3

import pytest

from app import ledger
from app.models import AuditTrailEntry, LedgerAppendOnlyError


# --- Canonical encoding -----------------------------------------------------

GOLDEN_FIELDS = {
    "prev_hash": "0" * 64,
    "sequence_no": 0,
    "payment_id": "pay_TT001a7kL2m",
    "batch_id": "batch_golden_0001",
    "timestamp_us": 1_756_100_000_000_000,
    "action": "RECORD_INGESTED",
    "actor": "system",
    "details": "Batch demo: ₹4,500.00 via upi — Aarav Sharma",
    "cost_paise": 0,
}

# Locked on 2026-08-25. Do not edit to make a failing test pass: a mismatch
# means the preimage format changed and every existing hash is now invalid.
GOLDEN_PREIMAGE_SHA256 = (
    "7a0dd1df19c90a5c5857e5e4351ea6d2e61467550453ce6f87aee1229e792c32"
)
GOLDEN_PREIMAGE_LENGTH = 268


def test_golden_preimage_is_stable():
    """The canonical preimage must not drift across runs or environments."""
    preimage = ledger.canonical(**GOLDEN_FIELDS)
    digest = hashlib.sha256(preimage).hexdigest()

    # Recompute twice in-process to catch any hidden nondeterminism.
    assert digest == hashlib.sha256(ledger.canonical(**GOLDEN_FIELDS)).hexdigest()
    assert len(preimage) == GOLDEN_PREIMAGE_LENGTH
    assert digest == GOLDEN_PREIMAGE_SHA256, (
        "Canonical preimage changed. If this was deliberate, bump "
        "ledger.PREIMAGE_VERSION and update GOLDEN_PREIMAGE_SHA256 — and be "
        "aware every previously written hash is now unverifiable."
    )


def test_length_prefix_prevents_field_shifting():
    """('ab','c') and ('a','bc') must not collide — the classic concat bug."""
    left = ledger.canonical(
        **{**GOLDEN_FIELDS, "action": "AB", "actor": "C"}
    )
    right = ledger.canonical(
        **{**GOLDEN_FIELDS, "action": "A", "actor": "BC"}
    )
    assert left != right


def test_none_and_empty_string_are_distinct():
    """A null detail must not hash the same as an empty one."""
    with_none = ledger.canonical(**{**GOLDEN_FIELDS, "details": None})
    with_empty = ledger.canonical(**{**GOLDEN_FIELDS, "details": ""})
    assert with_none != with_empty


def test_none_and_zero_are_distinct_for_optional_ints():
    absent = ledger.canonical(**GOLDEN_FIELDS, llm_input_tokens=None)
    zero = ledger.canonical(**GOLDEN_FIELDS, llm_input_tokens=0)
    assert absent != zero


def test_unicode_is_nfc_normalized():
    """Visually identical strings in NFC and NFD must hash identically."""
    import unicodedata

    nfc = "Namaste Aarav ji — ₹450.00"
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd or unicodedata.is_normalized("NFC", nfd)

    left = ledger.canonical(**{**GOLDEN_FIELDS, "details": nfc})
    right = ledger.canonical(**{**GOLDEN_FIELDS, "details": nfd})
    assert left == right


def test_cost_is_integer_paise_not_float():
    """Money must never enter the preimage as a float."""
    with pytest.raises((TypeError, AttributeError, OverflowError, ValueError)):
        # 24.5 has no exact integer representation; int() would silently
        # truncate, so the encoder rejects non-integral input.
        ledger.canonical(**{**GOLDEN_FIELDS, "cost_paise": 24.5})


# --- Append -----------------------------------------------------------------


def test_append_builds_a_linked_chain(db_session, payment_record):
    record = payment_record()
    db_session.add(record)
    db_session.commit()

    first = ledger.append_entry(
        db_session, payment_id=record.payment_id, action="RECORD_INGESTED"
    )
    second = ledger.append_entry(
        db_session, payment_id=record.payment_id, action="CLASSIFIED", cost_paise=50
    )

    assert first.sequence_no == 0
    assert first.prev_hash == ledger.GENESIS_PREV_HASH
    assert second.sequence_no == 1
    assert second.prev_hash == first.entry_hash

    result = ledger.verify_chain(db_session)
    assert result.valid is True
    assert result.entries_checked == 2
    assert result.head_hash == second.entry_hash


def test_verify_detects_tampered_content(db_session, payment_record):
    record = payment_record()
    db_session.add(record)
    db_session.commit()

    for index in range(5):
        ledger.append_entry(
            db_session, payment_id=record.payment_id, action=f"ACTION_{index}"
        )

    assert ledger.verify_chain(db_session).valid is True

    # Bypass the ORM guard the way a real tamperer would.
    db_session.execute(
        AuditTrailEntry.__table__.update()
        .where(AuditTrailEntry.sequence_no == 2)
        .values(details="silently altered")
    )
    db_session.commit()

    result = ledger.verify_chain(db_session)
    assert result.valid is False
    assert result.first_broken_sequence == 2
    assert "tampered" in result.reason.lower()


def test_verify_detects_deleted_entry(db_session, payment_record):
    record = payment_record()
    db_session.add(record)
    db_session.commit()

    for index in range(5):
        ledger.append_entry(
            db_session, payment_id=record.payment_id, action=f"ACTION_{index}"
        )

    db_session.execute(
        AuditTrailEntry.__table__.delete().where(AuditTrailEntry.sequence_no == 3)
    )
    db_session.commit()

    result = ledger.verify_chain(db_session)
    assert result.valid is False
    assert result.first_broken_sequence == 4
    assert "gap" in result.reason.lower()


def test_orm_update_is_blocked(db_session, payment_record):
    record = payment_record()
    db_session.add(record)
    db_session.commit()

    entry = ledger.append_entry(
        db_session, payment_id=record.payment_id, action="RECORD_INGESTED"
    )

    entry.details = "tampered via ORM"
    with pytest.raises(LedgerAppendOnlyError):
        db_session.commit()
    db_session.rollback()


def test_orm_delete_is_blocked(db_session, payment_record):
    record = payment_record()
    db_session.add(record)
    db_session.commit()

    entry = ledger.append_entry(
        db_session, payment_id=record.payment_id, action="RECORD_INGESTED"
    )

    db_session.delete(entry)
    with pytest.raises(LedgerAppendOnlyError):
        db_session.commit()
    db_session.rollback()


def test_prev_hash_unique_constraint_prevents_forks(db_session, payment_record):
    """The schema, not the writer, is what forbids a forked chain."""
    from sqlalchemy.exc import IntegrityError

    record = payment_record()
    db_session.add(record)
    db_session.commit()

    first = ledger.append_entry(
        db_session, payment_id=record.payment_id, action="A"
    )

    # Hand-craft a second entry claiming the same predecessor.
    fork = AuditTrailEntry(
        payment_id=record.payment_id,
        sequence_no=99,
        prev_hash=first.prev_hash,  # duplicate — must be rejected
        entry_hash="f" * 64,
        timestamp_us=ledger.now_us(),
        action="FORK",
        actor="attacker",
        cost_paise=0,
    )
    db_session.add(fork)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_verify_payment_scope(db_session, payment_record):
    record_a = payment_record(payment_id="pay_a")
    record_b = payment_record(payment_id="pay_b")
    db_session.add_all([record_a, record_b])
    db_session.commit()

    ledger.append_entry(db_session, payment_id="pay_a", action="A1")
    ledger.append_entry(db_session, payment_id="pay_b", action="B1")
    ledger.append_entry(db_session, payment_id="pay_a", action="A2")

    result = ledger.verify_payment(db_session, "pay_a")
    assert result.valid is True
    assert result.entries_checked == 2
    assert result.scope == "payment"


# --- Concurrency ------------------------------------------------------------


def test_concurrent_writers_cannot_fork_the_chain(tmp_path):
    """
    Four threads append simultaneously against a real file database.

    Correctness here does not come from a lock. A fork would require two rows
    sharing a prev_hash, and the UNIQUE index rejects that, so a losing writer
    retries. This is what makes the guarantee survive multiple uvicorn workers,
    where an in-process lock would do nothing at all.
    """
    import threading

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.database import configure_sqlite
    from app.models import Base, PaymentFailureRecord, install_append_only_triggers

    db_file = tmp_path / "concurrent.db"
    engine = create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )
    configure_sqlite(engine)
    Base.metadata.create_all(bind=engine)
    install_append_only_triggers(engine)
    Session = sessionmaker(bind=engine)

    seed = Session()
    seed.add(PaymentFailureRecord(
        payment_id="pay_concurrent", amount=100000, method="upi",
        merchant_id="m", customer_name="Test", customer_phone="+919999999999",
        error_reason="bank_technical_error",
    ))
    seed.commit()
    seed.close()

    writers, per_writer = 4, 25
    errors = []

    def write(worker_id: int):
        session = Session()
        try:
            for n in range(per_writer):
                ledger.append_entry(
                    session,
                    payment_id="pay_concurrent",
                    action=f"W{worker_id}_{n}",
                    cost_paise=1,
                )
        except Exception as exc:  # noqa: BLE001 - surfaced via assertion below
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=write, args=(i,)) for i in range(writers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"Writers raised: {errors}"

    check = Session()
    try:
        result = ledger.verify_chain(check)
        total = check.query(AuditTrailEntry).count()
    finally:
        check.close()
    engine.dispose()

    assert total == writers * per_writer
    assert result.valid is True, result.reason
    assert result.entries_checked == writers * per_writer
