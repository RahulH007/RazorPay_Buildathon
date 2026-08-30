"""
The recovery tick: what makes the escalation ladder reachable on live traffic.

The live path ingests a signed payment.failed, classifies it, and calls
execute_recovery exactly once (event_adapter.py). There is no loop. The
simulator has one - it re-consults policy before every rung, which is what
makes MAX_RETRIES reachable and the cost ceiling binding - and the live path
never had the equivalent. In this developer's own Test Mode database, no live
record has ever made a second attempt, and three have sat in INTERVENING since
2026-08-26 behind Payment Links that expired thirty minutes after they were
created.

This file tests the piece that closes that loop. The tick adds no decision
logic whatsoever: it decides only *which records are due*, then hands each to
the existing policy -> safety guard -> executor chain. So the tests here are
about selection and idempotence, not about what a recovery does.

Two properties get more attention than the rest, because both are ways this
could quietly do harm rather than quietly do nothing:

  * it must not close a record while a Payment Link it created can still be
    paid. settlement only transitions from INTERVENING/DIAGNOSED, so closing
    early would mean a late payment marks the link paid and loses the
    recovery outright;
  * it must not write a ledger entry per record per tick. The ledger is
    append-only and this is meant to be driven by cron, so a refusal written on
    every pass would grow the chain without bound.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app import ledger, razorpay_client, recovery_actions, recovery_tick, voice_pipeline
from app.config import IST, MAX_RETRIES
from app.consent import record_opt_out
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.recovery_actions import PAYMENT_LINK_EXPIRY_MINUTES
from app.recovery_tick import SkipReason

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
HELD = "UNMAPPED_REASON_HELD_FOR_REVIEW"


# --- Isolation --------------------------------------------------------------


@pytest.fixture(autouse=True)
def never_calls_anything(monkeypatch):
    """
    No Razorpay, no Gemini, no Sarvam - regardless of .env.

    conftest blocks the Razorpay client and pins llm_cache to replay, but it
    does not cover Sarvam: voice_pipeline.sarvam_tts posts to api.sarvam.ai
    whenever DEMO_MODE is false and the key is real. The voice rung is
    exercised below, so it is pinned here.
    """
    def boom_client(source):
        raise AssertionError(f"Razorpay client built (source={source!r})")

    def boom_link(source, payload):
        raise AssertionError(f"Payment Link creation attempted (source={source!r})")

    async def boom_tts(*args, **kwargs):
        raise AssertionError("Sarvam TTS called")

    monkeypatch.setattr(razorpay_client, "get_client", boom_client)
    monkeypatch.setattr(razorpay_client, "create_payment_link", boom_link)
    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", boom_link)
    monkeypatch.setattr(voice_pipeline, "sarvam_tts", boom_tts)
    monkeypatch.setattr(voice_pipeline, "DEMO_MODE", True)


@pytest.fixture(autouse=True)
def virtual_clock(monkeypatch):
    """
    Stamp ledger entries at simulated time rather than wall time.

    A tick compares its follow-up window against the timestamps of entries the
    executor wrote. Those are stamped by ledger.now_us(), so without this a
    tick "31 minutes later" would compare a simulated moment against an entry
    written at the real current second, and the whole file's results would
    depend on the hour it happened to run. ledger.set_clock exists for exactly
    this; the wrapper keeps it in step with whatever `now` a tick is given.
    """
    holder = {"now": NOW}
    ledger.set_clock(lambda: int(holder["now"].timestamp() * 1_000_000))
    real_advance = recovery_tick.advance_open_recoveries

    async def clocked(db, now=None, dry_run=False):
        holder["now"] = now or NOW
        return await real_advance(db, now=now, dry_run=dry_run)

    monkeypatch.setattr(recovery_tick, "advance_open_recoveries", clocked)
    try:
        yield holder
    finally:
        ledger.set_clock(None)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """
    Close the live Razorpay path so actions complete against the demo URL.

    Without this the outcome depends on the developer's PUBLIC_BASE_URL: the
    default is localhost, so a live-configured send is refused as a loopback
    callback and the assertions here would be testing that instead.
    """
    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: False)


# --- Builders ---------------------------------------------------------------


def live_record(db, payment_id="pay_tick_live_01", **overrides):
    values = {
        "payment_id": payment_id,
        "amount": 45000,
        "currency": "INR",
        "method": "card",
        "merchant_id": "acc_LiveMerchant01",
        "customer_name": "Live Customer",
        "customer_phone": "+919876500123",
        "error_reason": "authentication_failed",
        "error_description": "Issuer declined.",
        "failure_class": "AUTH_FRICTION",
        "recovery_state": "INTERVENING",
        "source": LIVE_SOURCE,
    }
    values.update(overrides)
    record = PaymentFailureRecord(**values)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def backdate_attempt(db, record, minutes_ago, action="WHATSAPP_LINK_SENT",
                     cost_paise=50):
    """Write an attempt entry stamped in the past, as a real one would be."""
    stamp = int((NOW - timedelta(minutes=minutes_ago)).timestamp() * 1_000_000)
    return ledger.append_entry(
        db,
        payment_id=record.payment_id,
        batch_id=record.batch_id,
        action=action,
        actor="system",
        details=f"backdated {minutes_ago}m",
        cost_paise=cost_paise,
        timestamp_us=stamp,
    )


def add_link(db, record, minutes_ago, status="created"):
    link = RazorpayPaymentLink(
        payment_id=record.payment_id,
        recovery_action_id="a" * 64,
        razorpay_payment_link_id=f"plink_{record.payment_id[-8:]}_{minutes_ago}",
        status=status,
        amount=record.amount,
        currency="INR",
        created_at=NOW - timedelta(minutes=minutes_ago),
    )
    db.add(link)
    db.commit()
    return link


def actions(db, payment_id=None):
    q = db.query(AuditTrailEntry)
    if payment_id:
        q = q.filter(AuditTrailEntry.payment_id == payment_id)
    return [e.action for e in q.order_by(AuditTrailEntry.sequence_no).all()]


def skip_reason(result, payment_id):
    for row in result["skipped"]:
        if row["payment_id"] == payment_id:
            return row["reason"]
    return None


# --- 1. The ladder actually advances ---------------------------------------


@pytest.mark.asyncio
async def test_a_stale_first_attempt_advances_to_the_second_rung(db_session):
    """
    The headline case, and the exact shape of the three records stuck in this
    project's live database: AUTH_FRICTION, one attempt, ladder of two.
    """
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=31)

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == [record.payment_id]
    assert len(result["advanced"]) == 1
    advanced = result["advanced"][0]
    assert advanced["action"] == "whatsapp_link"
    assert advanced["channel"] == "whatsapp_link"

    # Rung two really fired: two attempt entries now exist.
    assert actions(db_session).count("WHATSAPP_LINK_SENT") == 2
    assert record.recovery_state == "INTERVENING"


@pytest.mark.asyncio
async def test_the_ladder_then_exhausts_and_closes_the_record(db_session):
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)
    backdate_attempt(db_session, record, minutes_ago=60)

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["advanced"][0]["reason_code"] == "LADDER_EXHAUSTED"
    assert record.recovery_state == "FAILED_STOPPED"
    assert "POLICY_DECLINED_LADDER_EXHAUSTED" in actions(db_session)


@pytest.mark.asyncio
async def test_a_record_at_the_attempt_cap_is_closed_not_attempted(db_session):
    """TRANSIENT_TECHNICAL's ladder is longer than the cap, so the cap fires."""
    record = live_record(db_session, failure_class="TRANSIENT_TECHNICAL",
                         error_reason="bank_technical_error")
    for i in range(MAX_RETRIES):
        backdate_attempt(db_session, record, minutes_ago=60 + i,
                         action="RETRY_SILENT_ATTEMPT", cost_paise=0)

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["advanced"][0]["reason_code"] == "RETRY_CAP_REACHED"
    assert record.recovery_state == "FAILED_STOPPED"
    assert actions(db_session).count("RETRY_SILENT_ATTEMPT") == MAX_RETRIES


# --- 2 / 3 / 4. The skip rules ----------------------------------------------


@pytest.mark.asyncio
async def test_a_recent_attempt_is_left_alone(db_session):
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=5)
    before = db_session.query(AuditTrailEntry).count()

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == []
    assert skip_reason(result, record.payment_id) == SkipReason.ATTEMPT_TOO_RECENT
    assert db_session.query(AuditTrailEntry).count() == before


@pytest.mark.asyncio
async def test_the_window_boundary_is_inclusive_of_the_full_wait(db_session):
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=recovery_tick.FOLLOW_UP_AFTER_MINUTES)

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == [record.payment_id]


@pytest.mark.asyncio
async def test_a_held_for_review_record_is_skipped_entirely(db_session):
    """
    The safety guard would refuse it anyway. The point of skipping earlier is
    that a guard refusal writes a ledger row, and a cron-driven tick would then
    append one per record per pass forever.
    """
    record = live_record(db_session, error_reason="payment_cancelled",
                         recovery_state="DIAGNOSED")
    ledger.append_entry(db_session, payment_id=record.payment_id, action=HELD,
                        actor="system", details="held", cost_paise=0)
    before = db_session.query(AuditTrailEntry).count()

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == []
    assert skip_reason(result, record.payment_id) == SkipReason.HELD_FOR_REVIEW
    assert db_session.query(AuditTrailEntry).count() == before
    assert "SAFETY_GUARD_BLOCKED" not in actions(db_session)


@pytest.mark.asyncio
async def test_repeated_ticks_never_touch_a_held_record(db_session):
    record = live_record(db_session, error_reason="payment_failed",
                         recovery_state="DIAGNOSED")
    ledger.append_entry(db_session, payment_id=record.payment_id, action=HELD,
                        actor="system", details="held", cost_paise=0)
    before = db_session.query(AuditTrailEntry).count()

    for hour in range(6):
        await recovery_tick.advance_open_recoveries(
            db_session, now=NOW + timedelta(hours=hour)
        )

    assert db_session.query(AuditTrailEntry).count() == before
    assert record.recovery_state == "DIAGNOSED"


@pytest.mark.asyncio
async def test_a_payable_link_stops_the_record_being_chased(db_session):
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=25)
    add_link(db_session, record, minutes_ago=25)
    before = db_session.query(AuditTrailEntry).count()

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == []
    assert skip_reason(result, record.payment_id) == SkipReason.LINK_STILL_PAYABLE
    assert db_session.query(AuditTrailEntry).count() == before


@pytest.mark.asyncio
async def test_a_payable_link_also_stops_the_record_being_closed(db_session):
    """
    The correctness case, not the politeness one. settlement only transitions
    from INTERVENING/DIAGNOSED, so closing a record whose link can still be
    paid would mean a late payment marks the link paid and the recovery is
    lost. The ladder here is exhausted; the link is what must hold the record
    open.
    """
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)
    backdate_attempt(db_session, record, minutes_ago=20)
    add_link(db_session, record, minutes_ago=20)

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == []
    assert skip_reason(result, record.payment_id) == SkipReason.LINK_STILL_PAYABLE
    assert record.recovery_state == "INTERVENING"


@pytest.mark.asyncio
async def test_an_expired_link_no_longer_holds_the_record(db_session):
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)
    add_link(db_session, record, minutes_ago=PAYMENT_LINK_EXPIRY_MINUTES + 1)

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == [record.payment_id]


@pytest.mark.asyncio
async def test_a_paid_link_never_holds_a_record_open(db_session):
    """A settled link is not an outstanding one, however recently it was made."""
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)
    add_link(db_session, record, minutes_ago=1, status="paid")

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == [record.payment_id]


# --- Selection scope --------------------------------------------------------


@pytest.mark.parametrize("state", ["RECOVERED", "FAILED_STOPPED", "INGESTED"])
@pytest.mark.asyncio
async def test_only_open_diagnosed_or_intervening_records_are_considered(
    db_session, state
):
    record = live_record(db_session, recovery_state=state)
    backdate_attempt(db_session, record, minutes_ago=120)
    before = db_session.query(AuditTrailEntry).count()

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["considered"] == 0
    assert result["due"] == []
    assert result["skipped"] == []
    assert db_session.query(AuditTrailEntry).count() == before


@pytest.mark.asyncio
async def test_synthetic_records_are_never_touched(db_session, payment_record):
    """
    The tick is live-only. The simulator owns its own loop, and a tick that
    reached seeded records would move the demo's numbers.
    """
    record = payment_record(failure_class="AUTH_FRICTION",
                            recovery_state="INTERVENING",
                            error_reason="authentication_failed",
                            batch_id="batch_demo", source=SYNTHETIC_SOURCE)
    db_session.add(record)
    db_session.commit()
    backdate_attempt(db_session, record, minutes_ago=999)
    before = db_session.query(AuditTrailEntry).count()

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["considered"] == 0
    assert db_session.query(AuditTrailEntry).count() == before
    assert record.recovery_state == "INTERVENING"


@pytest.mark.asyncio
async def test_a_never_attempted_open_record_is_due_immediately(db_session):
    """A record deferred at ingestion has no attempt to wait behind."""
    record = live_record(db_session, recovery_state="DIAGNOSED")

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == [record.payment_id]
    assert "WHATSAPP_LINK_SENT" in actions(db_session)


# --- The safety guard still governs every tick attempt ----------------------


@pytest.mark.asyncio
async def test_an_unmapped_live_reason_is_never_advanced_by_the_tick(db_session):
    """
    Belt and braces with the held-for-review skip: a record carrying an
    unapproved code but *no* hold entry must still be refused, by the guard.
    """
    record = live_record(db_session, error_reason="payment_cancelled")
    backdate_attempt(db_session, record, minutes_ago=120)

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["due"] == [record.payment_id]
    assert result["advanced"][0]["reason_code"] == "SAFETY_GUARD_BLOCKED"
    # The one send present is the backdated prior attempt; the tick added none.
    assert actions(db_session).count("WHATSAPP_LINK_SENT") == 1
    assert "SAFETY_GUARD_BLOCKED" in actions(db_session)
    assert record.recovery_state == "INTERVENING"


@pytest.mark.asyncio
async def test_a_withdrawn_consent_closes_rather_than_contacts(db_session):
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)
    record_opt_out(db_session, phone=record.customer_phone, source="api",
                   payment_id=record.payment_id, channel="all")

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["advanced"][0]["reason_code"] == "CONSENT_WITHDRAWN"
    assert record.recovery_state == "FAILED_STOPPED"
    # Only the backdated prior attempt. Nothing new was sent to the contact.
    assert actions(db_session).count("WHATSAPP_LINK_SENT") == 1


# --- Deferrals resume, and do not flood the ledger --------------------------


@pytest.mark.asyncio
async def test_a_quiet_hours_deferral_resumes_when_the_window_opens(db_session):
    """
    Policy correctly leaves a deferred record open rather than closing it. On
    the live path, "later" never came - this is the loop that delivers it.
    """
    record = live_record(db_session, failure_class="B2B_RECEIVABLE",
                         error_reason="invoice_overdue_15d", amount=5000000,
                         invoice_id="inv_tick_01")
    night = datetime(2026, 8, 29, 23, 30, tzinfo=IST)
    stamp = int((night - timedelta(minutes=120)).timestamp() * 1_000_000)
    ledger.append_entry(db_session, payment_id=record.payment_id,
                        action="WHATSAPP_LINK_SENT", actor="system",
                        details="rung one", cost_paise=50, timestamp_us=stamp)

    deferred = await recovery_tick.advance_open_recoveries(db_session, now=night)

    assert deferred["advanced"][0]["reason_code"] == "QUIET_HOURS_DEFERRED"
    assert record.recovery_state == "INTERVENING"
    assert "VOICE_CALL_INITIATED" not in actions(db_session)

    morning = datetime(2026, 8, 30, 10, 0, tzinfo=IST)
    resumed = await recovery_tick.advance_open_recoveries(db_session, now=morning)

    assert resumed["advanced"][0]["channel"] == "hinglish_voice"
    assert "VOICE_CALL_INITIATED" in actions(db_session)


@pytest.mark.asyncio
async def test_a_deferred_record_is_not_re_polled_on_every_tick(db_session):
    """
    A refusal is a ledger entry. Under cron this would append one per record
    per pass, so a record refused inside the window is left alone exactly as a
    record attempted inside it would be.
    """
    record = live_record(db_session, failure_class="B2B_RECEIVABLE",
                         error_reason="invoice_overdue_15d", amount=5000000)
    night = datetime(2026, 8, 29, 23, 30, tzinfo=IST)
    stamp = int((night - timedelta(minutes=120)).timestamp() * 1_000_000)
    ledger.append_entry(db_session, payment_id=record.payment_id,
                        action="WHATSAPP_LINK_SENT", actor="system",
                        details="rung one", cost_paise=50, timestamp_us=stamp)

    await recovery_tick.advance_open_recoveries(db_session, now=night)
    after_first = db_session.query(AuditTrailEntry).count()

    for minutes in (1, 5, 10, 29):
        await recovery_tick.advance_open_recoveries(
            db_session, now=night + timedelta(minutes=minutes)
        )

    assert db_session.query(AuditTrailEntry).count() == after_first
    assert actions(db_session).count("POLICY_DECLINED_QUIET_HOURS_DEFERRED") == 1


# --- Idempotence ------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_ticks_at_the_same_moment_produce_one_attempt(db_session):
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)

    await recovery_tick.advance_open_recoveries(db_session, now=NOW)
    after_first = db_session.query(AuditTrailEntry).count()
    second = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert second["due"] == []
    assert db_session.query(AuditTrailEntry).count() == after_first
    assert actions(db_session).count("WHATSAPP_LINK_SENT") == 2


@pytest.mark.asyncio
async def test_a_full_lifecycle_over_successive_ticks(db_session):
    """One attempt in, ladder walked, record closed - and then left alone."""
    record = live_record(db_session, recovery_state="DIAGNOSED")

    first = await recovery_tick.advance_open_recoveries(db_session, now=NOW)
    second = await recovery_tick.advance_open_recoveries(
        db_session, now=NOW + timedelta(minutes=31))
    third = await recovery_tick.advance_open_recoveries(
        db_session, now=NOW + timedelta(minutes=62))
    fourth = await recovery_tick.advance_open_recoveries(
        db_session, now=NOW + timedelta(minutes=93))

    assert len(first["advanced"]) == 1
    assert len(second["advanced"]) == 1
    assert third["advanced"][0]["reason_code"] == "LADDER_EXHAUSTED"
    assert fourth["considered"] == 0

    assert record.recovery_state == "FAILED_STOPPED"
    assert actions(db_session).count("WHATSAPP_LINK_SENT") == 2


# --- Dry run ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(db_session):
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)
    before = db_session.query(AuditTrailEntry).count()
    head_before = ledger.get_head(db_session).entry_hash

    result = await recovery_tick.advance_open_recoveries(
        db_session, now=NOW, dry_run=True)

    assert result["dry_run"] is True
    assert result["due"] == [record.payment_id]
    assert result["advanced"] == []
    assert db_session.query(AuditTrailEntry).count() == before
    assert ledger.get_head(db_session).entry_hash == head_before
    assert record.recovery_state == "INTERVENING"


@pytest.mark.asyncio
async def test_dry_run_reports_the_same_selection_as_a_real_tick(db_session):
    due = live_record(db_session, payment_id="pay_tick_due")
    backdate_attempt(db_session, due, minutes_ago=120)
    recent = live_record(db_session, payment_id="pay_tick_recent")
    backdate_attempt(db_session, recent, minutes_ago=2)

    dry = await recovery_tick.advance_open_recoveries(db_session, now=NOW, dry_run=True)
    wet = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert dry["due"] == wet["due"] == ["pay_tick_due"]
    assert dry["considered"] == wet["considered"] == 2
    assert skip_reason(dry, "pay_tick_recent") == SkipReason.ATTEMPT_TOO_RECENT
    assert skip_reason(wet, "pay_tick_recent") == SkipReason.ATTEMPT_TOO_RECENT


@pytest.mark.asyncio
async def test_dry_run_makes_no_external_call_even_with_the_live_path_open(
    db_session, monkeypatch
):
    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: True)
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)

    result = await recovery_tick.advance_open_recoveries(
        db_session, now=NOW, dry_run=True)

    assert result["due"] == [record.payment_id]
    assert db_session.query(RazorpayPaymentLink).count() == 0


# --- Several records at once ------------------------------------------------


@pytest.mark.asyncio
async def test_a_tick_advances_every_due_record_and_reports_each(db_session):
    due_a = live_record(db_session, payment_id="pay_tick_a")
    backdate_attempt(db_session, due_a, minutes_ago=120)
    due_b = live_record(db_session, payment_id="pay_tick_b")
    backdate_attempt(db_session, due_b, minutes_ago=45)
    held = live_record(db_session, payment_id="pay_tick_held",
                       recovery_state="DIAGNOSED", error_reason="payment_failed")
    ledger.append_entry(db_session, payment_id=held.payment_id, action=HELD,
                        actor="system", details="held", cost_paise=0)
    recent = live_record(db_session, payment_id="pay_tick_recent")
    backdate_attempt(db_session, recent, minutes_ago=1)

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert result["considered"] == 4
    assert sorted(result["due"]) == ["pay_tick_a", "pay_tick_b"]
    assert len(result["advanced"]) == 2
    assert skip_reason(result, "pay_tick_held") == SkipReason.HELD_FOR_REVIEW
    assert skip_reason(result, "pay_tick_recent") == SkipReason.ATTEMPT_TOO_RECENT


@pytest.mark.asyncio
async def test_one_failing_record_does_not_abort_the_rest(db_session, monkeypatch):
    """
    A tick is a batch job. One record raising must not strand every record
    behind it, and the failure must be reported rather than swallowed.
    """
    first = live_record(db_session, payment_id="pay_tick_boom")
    backdate_attempt(db_session, first, minutes_ago=120)
    second = live_record(db_session, payment_id="pay_tick_ok")
    backdate_attempt(db_session, second, minutes_ago=120)

    real = recovery_tick.execute_recovery

    async def flaky(db, record, **kwargs):
        if record.payment_id == "pay_tick_boom":
            raise RuntimeError("razorpay timeout")
        return await real(db, record, **kwargs)

    monkeypatch.setattr(recovery_tick, "execute_recovery", flaky)

    result = await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert len(result["failed"]) == 1
    assert result["failed"][0]["payment_id"] == "pay_tick_boom"
    assert "razorpay timeout" in result["failed"][0]["error"]
    assert [a["payment_id"] for a in result["advanced"]] == ["pay_tick_ok"]


# --- Ledger -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_ledger_stays_valid_across_successive_ticks(db_session):
    record = live_record(db_session, recovery_state="DIAGNOSED")

    for minutes in (0, 31, 62, 93):
        await recovery_tick.advance_open_recoveries(
            db_session, now=NOW + timedelta(minutes=minutes))

    assert ledger.verify_chain(db_session).valid is True


# --- The endpoint -----------------------------------------------------------


@pytest.fixture
def client(db_session, monkeypatch):
    """
    Bound to the in-memory session, and never used as a context manager, so the
    app lifespan never runs and the developer's recoveros.db is untouched.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import recovery as recovery_routes

    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(recovery_routes, "SessionLocal", lambda: db_session)
    return TestClient(app)


def test_the_endpoint_defaults_to_a_dry_run(client, db_session):
    """
    A caller who forgets the flag must report, not act. The dangerous
    invocation is the one that has to be spelled out.
    """
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)
    before = db_session.query(AuditTrailEntry).count()

    response = client.post("/api/recovery/tick")
    body = response.json()

    assert response.status_code == 200
    assert body["dry_run"] is True
    assert body["due"] == [record.payment_id]
    assert body["advanced"] == []
    assert db_session.query(AuditTrailEntry).count() == before


def test_the_endpoint_acts_when_asked_explicitly(client, db_session):
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)

    body = client.post("/api/recovery/tick?dry_run=false").json()

    assert body["dry_run"] is False
    assert len(body["advanced"]) == 1
    assert actions(db_session).count("WHATSAPP_LINK_SENT") == 2


def test_the_endpoint_reports_skips_with_reasons(client, db_session):
    record = live_record(db_session, recovery_state="DIAGNOSED",
                         error_reason="payment_failed")
    ledger.append_entry(db_session, payment_id=record.payment_id, action=HELD,
                        actor="system", details="held", cost_paise=0)

    body = client.post("/api/recovery/tick").json()

    assert body["due"] == []
    assert body["skipped"][0]["reason"] == SkipReason.HELD_FOR_REVIEW
    assert "person" in body["skipped"][0]["detail"]


# --- The CLI ----------------------------------------------------------------


def test_the_cli_defaults_to_dry_run():
    from app.tools.run_tick import parse_args

    assert parse_args([]).execute is False
    assert parse_args(["--execute"]).execute is True
    assert parse_args(["--database-url", "sqlite:///x.db"]).database_url == "sqlite:///x.db"


def test_the_cli_renders_a_dry_run_without_claiming_action():
    from app.tools.run_tick import render

    text = render({
        "now": "2026-08-29T12:00:00+00:00", "dry_run": True,
        "follow_up_after_minutes": 30, "considered": 2,
        "due": ["pay_a"],
        "skipped": [{"payment_id": "pay_b", "reason": SkipReason.HELD_FOR_REVIEW,
                     "detail": "held"}],
        "advanced": [], "failed": [],
    })

    assert "DRY RUN" in text
    assert "pay_a" in text
    assert "HELD_FOR_REVIEW" in text
    assert "Nothing was written and nothing was sent." in text


def test_the_cli_renders_failures():
    from app.tools.run_tick import render

    text = render({
        "now": "2026-08-29T12:00:00+00:00", "dry_run": False,
        "follow_up_after_minutes": 30, "considered": 1,
        "due": ["pay_a"], "skipped": [],
        "advanced": [{"payment_id": "pay_a", "action": "whatsapp_link",
                      "channel": "whatsapp_link", "reason_code": "PROCEED",
                      "recovery_state": "INTERVENING"}],
        "failed": [{"payment_id": "pay_b", "error": "RuntimeError: boom"}],
    })

    assert "EXECUTE" in text
    assert "FAILED (1)" in text
    assert "RuntimeError: boom" in text
    assert "Nothing was written" not in text


@pytest.mark.asyncio
async def test_the_tick_writes_no_ledger_entries_of_its_own(db_session):
    """
    Every entry on a tick comes from the existing executor, policy or guard.
    The tick is a scheduler, and a scheduler that narrates itself into an
    append-only chain is noise a reviewer has to read past.
    """
    record = live_record(db_session)
    backdate_attempt(db_session, record, minutes_ago=120)

    await recovery_tick.advance_open_recoveries(db_session, now=NOW)

    assert not any(a.startswith("TICK") for a in actions(db_session))
