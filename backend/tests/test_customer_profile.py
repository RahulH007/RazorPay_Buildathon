"""
Why this customer, why this channel, why now.

The system could already say what went wrong and what it would do about it. It
could not say anything about the person on the other end - so a customer who
has ignored two WhatsApp links and paid twice after a voice call was offered a
third WhatsApp link, and the ledger recorded no sign that anyone had noticed.

Everything needed to notice was already stored. Payments carry a contact, a
method and an outcome; the chain records which intervention preceded each
recovery and when it settled. This is a read over that, keyed on the normalized
phone number the consent registry already treats as a customer's identity.

Two rules the tests exist to hold:

    Nothing is invented. Every line of evidence names a count that can be
    recomputed from the records it came from, and a customer with no history
    gets an explicit "no prior payments" rather than a confident-sounding
    guess assembled from one data point.

    Nothing is authorised. The advisory may recommend a channel the policy
    ladder will not use, and when it does, the executor follows the ladder.
    That case is tested directly, because an advisory nobody can override is
    not an advisory.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import ast
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import customer_profile, ledger, recovery_actions
from app.config import IST
from app.database import Base
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.policy import ATTEMPT_LADDER
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE

PHONE = "+919812345678"
OTHER_PHONE = "+919800000001"

WA = "WHATSAPP_LINK_SENT"
VOICE = "VOICE_CALL_INITIATED"
UPI = "MANDATE_RESEQUENCED"
RETRY = "RETRY_SILENT_ATTEMPT"
RECOVERED_FROM_INTERVENING = "STATE_INTERVENING_TO_RECOVERED"

COST = {WA: 50, VOICE: 200, UPI: 50, RETRY: 0}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def history(db, payment_id, *, phone=PHONE, method="card", state="RECOVERED",
            trail=(), failure_class="AUTH_FRICTION",
            error_reason="authentication_failed", amount=100_000,
            settled_at=None, source=LIVE_SOURCE, batch_id=None):
    """One past payment plus the ledger trail it actually left."""
    record = PaymentFailureRecord(
        payment_id=payment_id, amount=amount, currency="INR", method=method,
        merchant_id="m", customer_name="Priya Menon", customer_phone=phone,
        error_reason=error_reason, error_description="d",
        failure_class=failure_class, recovery_state=state, source=source,
        batch_id=batch_id, arm="treated",
    )
    db.add(record)
    db.commit()

    for action in trail:
        stamp = None
        if action == RECOVERED_FROM_INTERVENING and settled_at is not None:
            stamp = int(settled_at.timestamp() * 1_000_000)
        ledger.append_entry(
            db, payment_id=payment_id, batch_id=batch_id, action=action,
            actor="system", details="history fixture",
            cost_paise=COST.get(action, 0), timestamp_us=stamp,
        )
    return record


def open_record(db, payment_id="pay_now", *, phone=PHONE, failure_class="AUTH_FRICTION",
                error_reason="authentication_failed", state="DIAGNOSED",
                source=LIVE_SOURCE, batch_id=None, method="card"):
    return history(db, payment_id, phone=phone, method=method, state=state,
                   trail=(), failure_class=failure_class,
                   error_reason=error_reason, source=source, batch_id=batch_id)


def at(hour, day=26):
    return datetime(2026, 8, day, hour, 0, tzinfo=IST)


async def _template(record, link_url):
    return f"template for {record.customer_name}", {}, None


@pytest.fixture(autouse=True)
def no_generation(monkeypatch):
    monkeypatch.setattr(recovery_actions, "generate_whatsapp_message", _template)


# =============================================================================
# A customer with a strong, consistent history
# =============================================================================


@pytest.fixture
def loyal_to_voice(db):
    """
    Three resolved payments from one contact. Voice recovered two of two;
    WhatsApp was tried twice and recovered nothing.
    """
    history(db, "pay_h1", trail=[WA], state="FAILED_STOPPED")
    history(db, "pay_h2", method="upi",
            trail=[WA, VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(14))
    history(db, "pay_h3", method="upi",
            trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(15, day=27))
    return db


def test_a_strong_channel_preference_is_read_off_the_ledger(loyal_to_voice, db):
    record = open_record(db)

    profile = customer_profile.build_profile(db, record)

    assert profile.payments_seen == 3
    assert profile.recovered == 2
    assert profile.channels["hinglish_voice"] == {"attempts": 2, "recovered": 2}
    assert profile.channels["whatsapp_link"] == {"attempts": 2, "recovered": 0}
    assert profile.effective_channel == "hinglish_voice"
    assert profile.sufficiency == customer_profile.Sufficiency.SUFFICIENT


def test_the_advisory_recommends_the_channel_that_actually_worked(loyal_to_voice, db):
    record = open_record(db)

    advisory = customer_profile.advise(db, record, now=at(11))

    assert advisory.recommended_channel == "hinglish_voice"
    assert advisory.confidence == 0.75          # base 0.45 + 0.15 per resolved, 2 of them
    assert "hinglish_voice" in advisory.rationale
    assert advisory.advisory is True


def test_every_line_of_evidence_names_a_number_that_can_be_rechecked(
        loyal_to_voice, db):
    """
    Evidence is only evidence if a reviewer can recompute it. Each line carries
    the count it came from, and the counts agree with the profile.
    """
    record = open_record(db)
    advisory = customer_profile.advise(db, record, now=at(11))
    joined = " ".join(advisory.evidence)

    assert "3 previous payment" in joined
    assert "2 recovered" in joined
    assert "hinglish_voice: 2 attempt" in joined
    assert "whatsapp_link: 2 attempt" in joined


def test_past_recovery_timing_is_reported_only_as_an_observation(loyal_to_voice, db):
    """
    Two settlements is enough to state an hour, not enough to hold a payment
    back for one. The hour appears in the timing note; act_now stays true.
    """
    record = open_record(db)

    timing = customer_profile.advise(db, record, now=at(11)).timing

    assert timing["act_now"] is True
    assert timing["not_before"] is None
    assert "14" in timing["why"] or "15" in timing["why"]


def test_recovered_methods_are_listed_and_failed_ones_are_not(loyal_to_voice, db):
    record = open_record(db)

    profile = customer_profile.build_profile(db, record)

    assert profile.recovered_methods == {"upi": 2}
    assert profile.methods == {"card": 1, "upi": 2}


# =============================================================================
# Mixed history
# =============================================================================


def test_a_mixed_history_names_the_channel_with_the_most_wins(db):
    history(db, "pay_m1", trail=[WA, RECOVERED_FROM_INTERVENING], settled_at=at(10))
    history(db, "pay_m2", trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(16))
    history(db, "pay_m3", trail=[WA, RECOVERED_FROM_INTERVENING], settled_at=at(11))
    record = open_record(db)

    profile = customer_profile.build_profile(db, record)
    advisory = customer_profile.advise(db, record, now=at(12))

    assert profile.channels["whatsapp_link"]["recovered"] == 2
    assert profile.channels["hinglish_voice"]["recovered"] == 1
    assert profile.effective_channel == "whatsapp_link"
    assert advisory.confidence == 0.90          # capped at three resolved priors


def test_a_history_with_no_recovery_at_all_names_no_effective_channel(db):
    """
    Three failures is history, but it is not evidence for a channel. Saying
    "prefers WhatsApp" because WhatsApp is the only thing ever tried on someone
    who never paid would be inventing a preference out of a habit of ours.
    """
    for i in range(3):
        history(db, f"pay_f{i}", trail=[WA], state="FAILED_STOPPED")
    record = open_record(db)

    profile = customer_profile.build_profile(db, record)
    advisory = customer_profile.advise(db, record, now=at(12))

    assert profile.payments_seen == 3
    assert profile.recovered == 0
    assert profile.effective_channel is None
    assert profile.sufficiency == customer_profile.Sufficiency.NONE
    assert advisory.confidence == 0.0
    assert "whatsapp_link: 3 attempts, 0 recoveries." in " ".join(advisory.evidence)


def test_a_repeated_failure_reason_is_surfaced(db):
    history(db, "pay_r1", trail=[WA, RECOVERED_FROM_INTERVENING], settled_at=at(10),
            error_reason="incorrect_otp")
    history(db, "pay_r2", trail=[WA, RECOVERED_FROM_INTERVENING], settled_at=at(10),
            error_reason="incorrect_otp")
    record = open_record(db, error_reason="incorrect_otp")

    profile = customer_profile.build_profile(db, record)
    advisory = customer_profile.advise(db, record, now=at(12))

    assert profile.failure_reasons["incorrect_otp"] == 2
    assert "incorrect_otp" in " ".join(advisory.evidence)


# =============================================================================
# No history, and insufficient history
# =============================================================================


def test_a_new_customer_is_described_as_a_new_customer(db):
    record = open_record(db)

    profile = customer_profile.build_profile(db, record)
    advisory = customer_profile.advise(db, record, now=at(12))

    assert profile.payments_seen == 0
    assert profile.effective_channel is None
    assert profile.sufficiency == customer_profile.Sufficiency.NONE
    assert advisory.confidence == 0.0
    assert advisory.evidence == [customer_profile.NO_HISTORY_EVIDENCE]
    assert "no prior payments" in advisory.sufficiency_reason.lower()


def test_a_new_customer_falls_back_to_the_ladder_and_says_so(db):
    record = open_record(db)

    advisory = customer_profile.advise(db, record, now=at(12))

    assert advisory.recommended_channel == ATTEMPT_LADDER["AUTH_FRICTION"][0]
    assert advisory.overridden_by_policy is False
    assert "ladder" in advisory.rationale.lower()


def test_one_recovery_is_thin_rather_than_sufficient(db):
    """
    A single data point is not a preference. It is reported, with lower
    confidence and a sufficiency level that says what it is.
    """
    history(db, "pay_one", trail=[WA, RECOVERED_FROM_INTERVENING], settled_at=at(10))
    record = open_record(db)

    profile = customer_profile.build_profile(db, record)
    advisory = customer_profile.advise(db, record, now=at(12))

    assert profile.sufficiency == customer_profile.Sufficiency.THIN
    assert advisory.confidence == 0.60
    assert "1 resolved" in advisory.sufficiency_reason


def test_one_recovery_gives_no_timing_claim(db):
    """One settlement is an anecdote, not an hour."""
    history(db, "pay_one", trail=[WA, RECOVERED_FROM_INTERVENING], settled_at=at(3))
    record = open_record(db)

    timing = customer_profile.advise(db, record, now=at(12)).timing

    assert "03" not in timing["why"]
    assert timing["act_now"] is True


def test_another_customers_history_is_never_borrowed(db):
    history(db, "pay_theirs", phone=OTHER_PHONE,
            trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(10))
    record = open_record(db)

    profile = customer_profile.build_profile(db, record)

    assert profile.payments_seen == 0
    assert profile.effective_channel is None


def test_the_record_being_advised_on_is_not_its_own_evidence(db):
    """
    Circular by construction if missed: a record that already carries an
    attempt would be counted as proof that the channel works on this customer.
    """
    record = history(db, "pay_self", trail=[WA, RECOVERED_FROM_INTERVENING],
                     settled_at=at(10))

    profile = customer_profile.build_profile(db, record)

    assert profile.payments_seen == 0
    assert profile.channels == {}


def test_a_punctuated_number_is_the_same_customer(db):
    """
    The formats that actually appear. "+91 98123-45678" and "9812345678" share
    no common suffix as strings, so anything matching on the stored text drops
    one of them - and drops it before normalization can have an opinion.
    """
    history(db, "pay_fmt1", phone="+91 98123-45678",
            trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(10))
    history(db, "pay_fmt2", phone="(0) 98123 45678",
            trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(11))
    record = open_record(db, phone="9812345678")

    profile = customer_profile.build_profile(db, record)

    assert profile.payments_seen == 2
    assert profile.effective_channel == "hinglish_voice"


def test_a_phone_written_three_different_ways_is_one_customer(db):
    """
    The registry already treats these as one identity; a profile that did not
    would silently split a customer's history in half.
    """
    history(db, "pay_p1", phone="+919812345678",
            trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(10))
    history(db, "pay_p2", phone="09812345678",
            trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(11))
    record = open_record(db, phone="9812345678")

    profile = customer_profile.build_profile(db, record)

    assert profile.payments_seen == 2
    assert profile.effective_channel == "hinglish_voice"


# =============================================================================
# Why now
# =============================================================================


def test_a_voice_recommendation_inside_quiet_hours_is_deferred(loyal_to_voice, db):
    record = open_record(db)

    timing = customer_profile.advise(db, record, now=at(23)).timing

    assert timing["act_now"] is False
    assert timing["not_before"] is not None
    assert "quiet hours" in timing["why"].lower()


def test_a_stated_promise_to_pay_outranks_everything_else(loyal_to_voice, db):
    record = open_record(db)
    record.promise_to_pay_at = datetime(2026, 9, 2, 12, 0)
    db.commit()

    timing = customer_profile.advise(db, record, now=at(11)).timing

    assert timing["act_now"] is False
    assert "2026-09-02" in timing["why"]


def test_a_recent_attempt_holds_the_next_one_back(db):
    record = open_record(db, state="INTERVENING")
    ledger.append_entry(
        db, payment_id=record.payment_id, batch_id=None, action=WA,
        actor="system", details="just sent", cost_paise=50,
        timestamp_us=int(at(11).timestamp() * 1_000_000),
    )

    timing = customer_profile.advise(db, record, now=at(11) + timedelta(minutes=5)).timing

    assert timing["act_now"] is False
    assert "follow-up window" in timing["why"].lower()


# =============================================================================
# Advisory only - policy and the guard stay in charge
# =============================================================================


@pytest.mark.asyncio
async def test_policy_overrides_a_recommendation_it_does_not_share(
        loyal_to_voice, db):
    """
    THE override test. This customer pays after voice calls and ignores links,
    and the advisory says so. The record is AUTH_FRICTION, whose ladder opens
    with whatsapp_link - so a WhatsApp link is what goes out.

    The recommendation is not discarded quietly: it is recorded, it is marked
    as overridden, and the ledger holds both it and the decision that beat it.
    """
    record = open_record(db)

    advisory = customer_profile.advise(db, record, now=at(11))
    assert advisory.recommended_channel == "hinglish_voice"
    assert advisory.policy_ladder_next == "whatsapp_link"
    assert advisory.overridden_by_policy is True

    result = await recovery_actions.execute_recovery(db, record, source=LIVE_SOURCE)

    assert result["action"] == "whatsapp_link"
    assert result["decision"]["channel"] == "whatsapp_link"
    trail = [e.action for e in db.query(AuditTrailEntry)
             .filter(AuditTrailEntry.payment_id == record.payment_id)]
    assert VOICE not in trail


@pytest.mark.asyncio
async def test_a_recommendation_alone_executes_nothing(db):
    """
    A confident advisory on a record policy will not act on. Recording it
    changes no state, spends nothing, and contacts nobody.
    """
    history(db, "pay_hd1", trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(10))
    history(db, "pay_hd2", trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(11))
    record = open_record(db, failure_class="HARD_DECLINE",
                         error_reason="compliance_violation")

    advisory = customer_profile.advise(db, record, now=at(12))
    customer_profile.record_advisory(db, record, advisory)
    result = await recovery_actions.execute_recovery(db, record, source=LIVE_SOURCE)

    assert advisory.confidence >= 0.75
    assert result["action"] == "declined"
    assert result["reason_code"] == "HARD_DECLINE"
    assert db.query(RazorpayPaymentLink).count() == 0
    # Scoped to this record: the fixture's two past voice calls cost 400p
    # between them, and counting those here would be counting history as if it
    # were something this call spent.
    spent = sum(e.cost_paise or 0 for e in db.query(AuditTrailEntry)
                .filter(AuditTrailEntry.payment_id == record.payment_id))
    assert spent == 0


def test_the_profile_module_imports_nothing_that_can_act():
    """
    Structural. A module that cannot import an executor cannot call one,
    whatever it is edited into later.
    """
    import app.customer_profile as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)

    forbidden = {"app.recovery_actions", "app.razorpay_client", "app.voice_pipeline",
                 "app.settlement", "app.recovery_tick", "razorpay", "httpx", "requests"}
    assert not (imported & forbidden), imported & forbidden


def test_it_can_only_ever_name_a_channel_the_ladder_contains(loyal_to_voice, db):
    rungs = {c for steps in ATTEMPT_LADDER.values() for c in steps}
    record = open_record(db)

    advisory = customer_profile.advise(db, record, now=at(11))

    assert advisory.recommended_channel in rungs
    for channel in customer_profile.build_profile(db, record).channels:
        assert channel in rungs


def test_a_channel_outside_the_ladder_is_refused_even_if_history_names_it(
        db, monkeypatch):
    """
    Defence in depth, exercised through its seam.

    The economics module only ever names ladder rungs today, so this guard is
    unreachable by the ordinary path - which is precisely why it needs a test:
    an unreachable guard is indistinguishable from a deleted one until the day
    something upstream changes.
    """
    history(db, "pay_x1", trail=[WA, RECOVERED_FROM_INTERVENING], settled_at=at(10))
    history(db, "pay_x2", trail=[WA, RECOVERED_FROM_INTERVENING], settled_at=at(11))
    record = open_record(db)

    monkeypatch.setattr(customer_profile, "by_intervention", lambda db_, records: {
        "interventions": {
            "carrier_pigeon": {"attempts": 4, "recovered": 4},
        }
    })

    profile = customer_profile.build_profile(db, record)
    advisory = customer_profile.advise(db, record, now=at(12))

    assert profile.effective_channel == "carrier_pigeon"      # history says so
    assert advisory.recommended_channel == ATTEMPT_LADDER["AUTH_FRICTION"][0]
    assert advisory.overridden_by_policy is False


def test_recording_an_advisory_costs_nothing_and_moves_no_state(loyal_to_voice, db):
    record = open_record(db)

    entry = customer_profile.record_advisory(
        db, record, customer_profile.advise(db, record, now=at(11)))

    assert entry.cost_paise == 0
    assert entry.action == customer_profile.ADVISORY_ACTION
    assert record.recovery_state == "DIAGNOSED"
    assert ledger.verify_chain(db).valid is True


def test_the_advisory_is_attributed_to_the_layer_that_actually_produced_it(
        loyal_to_voice, db):
    """
    Not "llm_agent". This reading is computed from the customer's own records,
    and a ledger whose purpose is attribution must not credit a model for
    arithmetic it did not do.
    """
    record = open_record(db)

    entry = customer_profile.record_advisory(
        db, record, customer_profile.advise(db, record, now=at(11)))

    # Asserted literally, not against the constant: comparing the entry to the
    # same constant that produced it would pass no matter what the constant
    # said, which is exactly the mistake this test exists to prevent.
    assert entry.actor == "profile_engine"
    assert entry.actor != "llm_agent"
    assert customer_profile.ADVISORY_BANNER in entry.details


def test_the_advisory_is_not_an_attempt_and_not_a_diagnosis_confidence(db):
    from app import safety_guard
    from app.guardrails import ATTEMPT_ACTIONS
    from app.intervention_economics import INTERVENTION_BY_ACTION

    assert customer_profile.ADVISORY_ACTION not in ATTEMPT_ACTIONS
    assert customer_profile.ADVISORY_ACTION not in INTERVENTION_BY_ACTION
    assert customer_profile.ADVISORY_ACTION not in safety_guard.DIAGNOSIS_CONFIDENCE_ACTIONS


# =============================================================================
# Read-back, feedback, and the APIs
# =============================================================================


def test_a_new_outcome_changes_the_next_recommendation(db):
    """
    The feedback loop, stated as a test. The profile is a read over the ledger,
    so an intervention that lands today is evidence tomorrow without anything
    being written back.
    """
    history(db, "pay_fb1", trail=[WA, RECOVERED_FROM_INTERVENING], settled_at=at(10))
    record = open_record(db)
    assert customer_profile.advise(db, record, now=at(12)).recommended_channel \
        == "whatsapp_link"

    history(db, "pay_fb2", trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(11))
    history(db, "pay_fb3", trail=[VOICE, RECOVERED_FROM_INTERVENING], settled_at=at(12))

    assert customer_profile.advise(db, record, now=at(12)).recommended_channel \
        == "hinglish_voice"


def test_the_advisory_survives_a_round_trip_through_the_ledger(loyal_to_voice, db):
    record = open_record(db)
    advisory = customer_profile.advise(db, record, now=at(11))

    customer_profile.record_advisory(db, record, advisory)

    assert customer_profile.latest_for(db, record.payment_id) == advisory.to_dict()


def test_a_record_with_no_recorded_advisory_reads_back_as_none(db):
    record = open_record(db)

    assert customer_profile.latest_for(db, record.payment_id) is None


@pytest.mark.asyncio
async def test_the_recovery_api_serves_the_insight(loyal_to_voice, db, monkeypatch):
    from app.routes import recovery as recovery_routes

    record = open_record(db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(recovery_routes, "SessionLocal", lambda: db)

    payload = await recovery_routes.get_recovery_record(record.payment_id)
    insight = payload["customer_insight"]

    assert insight["recommended_channel"] == "hinglish_voice"
    assert insight["advisory"] is True
    assert insight["notice"] == customer_profile.ADVISORY_BANNER
    assert insight["evidence"]


@pytest.mark.asyncio
async def test_the_audit_api_serves_the_insight_too(loyal_to_voice, db, monkeypatch):
    """The drawer already fetches this endpoint; a second request would be waste."""
    from app.routes import audit as audit_routes

    record = open_record(db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(audit_routes, "SessionLocal", lambda: db)

    payload = await audit_routes.get_audit_trail(record.payment_id)

    assert payload["customer_insight"]["recommended_channel"] == "hinglish_voice"


@pytest.mark.asyncio
async def test_the_live_ingest_path_records_one_advisory(db, monkeypatch):
    from app import event_adapter, llm_cache

    monkeypatch.setattr(llm_cache, "call", lambda **kw: (_ for _ in ()).throw(
        llm_cache.CacheMiss("not recorded")))

    normalized = event_adapter.normalize_razorpay_payment_failed({
        "account_id": "acc", "payload": {"payment": {"entity": {
            "id": "pay_live_ingest", "amount": 45000, "currency": "INR",
            "method": "upi", "contact": PHONE,
            "error_reason": "authentication_failed", "error_description": "d",
        }}},
    })
    await event_adapter.ingest_and_process(db, normalized)

    trail = [e.action for e in db.query(AuditTrailEntry)
             .filter(AuditTrailEntry.payment_id == "pay_live_ingest")
             .order_by(AuditTrailEntry.sequence_no)]

    assert trail.count(customer_profile.ADVISORY_ACTION) == 1
    assert customer_profile.latest_for(db, "pay_live_ingest") is not None


# =============================================================================
# Nothing else moved
# =============================================================================


@pytest.mark.asyncio
async def test_a_synthetic_run_writes_no_advisory_and_costs_the_same(db):
    """
    The demo path is untouched: the advisory is written on the live ingest path
    only, and computed on read everywhere else. A synthetic batch's ledger is
    exactly what it was.
    """
    record = open_record(db, payment_id="pay_synth", source=SYNTHETIC_SOURCE,
                         batch_id="batch_profile")

    outcomes = []
    while record.recovery_state not in ("RECOVERED", "FAILED_STOPPED"):
        result = await recovery_actions.execute_recovery(db, record,
                                                         source=SYNTHETIC_SOURCE)
        outcomes.append(result["action"])
        if result["action"] in ("declined", "no_action"):
            break

    trail = [e.action for e in db.query(AuditTrailEntry)]
    assert outcomes == ["whatsapp_link", "whatsapp_link", "declined"]
    assert customer_profile.ADVISORY_ACTION not in trail
    assert sum(e.cost_paise or 0 for e in db.query(AuditTrailEntry)) == 100


@pytest.mark.asyncio
async def test_nothing_here_reaches_an_external_api(loyal_to_voice, db):
    from app import llm_cache, voice_pipeline

    record = open_record(db)
    customer_profile.record_advisory(
        db, record, customer_profile.advise(db, record, now=at(11)))

    assert llm_cache.DEMO_MODE is True
    assert voice_pipeline.DEMO_MODE is True
    assert db.query(RazorpayPaymentLink).count() == 0
