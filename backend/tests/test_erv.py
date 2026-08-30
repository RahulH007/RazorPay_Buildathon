"""
Expected Recovery Value: is this attempt worth making?

The policy engine already refused actions that cost more than the margin they
could recover, using a flat per-class rate from config. That check is a good
one and is untouched here. What it cannot do is notice that *this* channel has
been tried on *this* customer four times and has never once been paid - the
flat rate says AUTH_FRICTION recovers 40% of the time, so a fifth WhatsApp
message keeps looking worthwhile forever.

ERV closes that. It values the attempt at

    expected_value = amount x observed success probability
    expected_net   = expected_value - action cost

and refuses when expected_net <= 0. The probability comes from history that
already exists - this customer's own outcomes first, then this channel's
outcomes across every record - and falls back to the deterministic per-class
rate that was always there, clearly labelled as an estimate rather than an
observation. No model, no new service, no new table.

Two things the tests hold hardest:

    ERV is an additional constraint, never a replacement. Every existing
    refusal - hard decline, retry cap, ladder exhaustion, CAC ceiling, the
    original margin check, consent, quiet hours - is evaluated first and still
    wins, so a compliance stop is never reported as an economic one. The
    safety guard runs afterwards and can still refuse an action ERV approved.

    Arithmetic is integer. Probability is basis points and value is paise,
    because these numbers reach the ledger's hash preimage and float
    arithmetic is not reproducible across runtimes.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import erv, ledger, policy, recovery_actions
from app.config import CHANNEL_COSTS_PAISE, RECOVERY_RATES
from app.database import Base
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.policy import ReasonCode, decide_next_action
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.state_machine import VALID_TRANSITIONS

PHONE = "+919812345678"
WA = "WHATSAPP_LINK_SENT"
VOICE = "VOICE_CALL_INITIATED"
RECOVERED = "STATE_INTERVENING_TO_RECOVERED"
COST = {WA: 50, VOICE: 200}

# The seeded dataset's smallest payment. Every ERV assertion about the demo
# rests on this, so it is named rather than sprinkled through the tests.
SMALLEST_SYNTHETIC_AMOUNT = 45_000     # Rs 450


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


def make(db, payment_id, *, phone=PHONE, amount=100_000, state="DIAGNOSED",
         failure_class="AUTH_FRICTION", error_reason="authentication_failed",
         trail=(), source=LIVE_SOURCE, batch_id=None):
    record = PaymentFailureRecord(
        payment_id=payment_id, amount=amount, currency="INR", method="card",
        merchant_id="m", customer_name="Priya Menon", customer_phone=phone,
        error_reason=error_reason, error_description="d",
        failure_class=failure_class, recovery_state=state, source=source,
        batch_id=batch_id, arm="treated",
    )
    db.add(record)
    db.commit()
    for action in trail:
        ledger.append_entry(db, payment_id=payment_id, batch_id=batch_id,
                            action=action, actor="system", details="fixture",
                            cost_paise=COST.get(action, 0))
    return record


async def _template(record, link_url):
    return f"template for {record.customer_name}", {}, None


@pytest.fixture(autouse=True)
def no_generation(monkeypatch):
    monkeypatch.setattr(recovery_actions, "generate_whatsapp_message", _template)


def actions(db, payment_id):
    return [e.action for e in db.query(AuditTrailEntry)
            .filter(AuditTrailEntry.payment_id == payment_id)
            .order_by(AuditTrailEntry.sequence_no)]


# =============================================================================
# The arithmetic
# =============================================================================


def test_expected_value_is_the_amount_times_the_probability(db):
    record = make(db, "pay_ev", amount=500_000)          # Rs 5,000

    estimate = erv.evaluate(db, record, "whatsapp_link", 50, probability_bp=6200)

    assert estimate.probability_bp == 6200               # 62%
    assert estimate.expected_value_paise == 310_000      # Rs 3,100
    assert estimate.cost_paise == 50
    assert estimate.expected_net_paise == 309_950        # Rs 3,049.50
    assert estimate.viable is True


def test_a_negative_expected_net_is_not_viable(db):
    record = make(db, "pay_neg", amount=5_000)           # Rs 50

    estimate = erv.evaluate(db, record, "whatsapp_link", 50, probability_bp=80)

    assert estimate.expected_value_paise == 40           # 0.8% of Rs 50
    assert estimate.expected_net_paise == -10
    assert estimate.viable is False


def test_exactly_zero_expected_net_is_not_viable(db):
    """
    The boundary is <= 0, not < 0. An attempt that breaks even in expectation
    still costs real money and real customer patience for nothing.
    """
    record = make(db, "pay_zero", amount=5_000)

    estimate = erv.evaluate(db, record, "whatsapp_link", 50, probability_bp=100)

    assert estimate.expected_value_paise == 50           # exactly the cost
    assert estimate.expected_net_paise == 0
    assert estimate.viable is False


def test_one_paise_above_break_even_is_viable(db):
    """The other side of the same boundary, so the comparison cannot drift."""
    record = make(db, "pay_edge", amount=5_100)

    estimate = erv.evaluate(db, record, "whatsapp_link", 50, probability_bp=100)

    assert estimate.expected_net_paise == 1
    assert estimate.viable is True


def test_the_arithmetic_is_integer_throughout(db):
    """
    These numbers reach the ledger's hash preimage. A float would make the same
    decision hash differently on another runtime, which is the one thing this
    project's audit trail may not do.
    """
    record = make(db, "pay_int", amount=333_333)

    estimate = erv.evaluate(db, record, "whatsapp_link", 50, probability_bp=3333)

    assert isinstance(estimate.probability_bp, int)
    assert isinstance(estimate.expected_value_paise, int)
    assert isinstance(estimate.expected_net_paise, int)
    assert estimate.expected_value_paise == 333_333 * 3333 // 10_000


def test_a_free_channel_is_never_blocked_by_erv(db):
    record = make(db, "pay_free", failure_class="TRANSIENT_TECHNICAL",
                  error_reason="bank_technical_error")

    estimate = erv.evaluate(db, record, "silent_retry", 0, probability_bp=1)

    assert estimate.cost_paise == 0
    assert estimate.expected_net_paise > 0
    assert estimate.viable is True


# =============================================================================
# Where the probability comes from
# =============================================================================


def test_a_customers_own_outcomes_are_used_when_there_are_enough(db):
    """
    Four WhatsApp links to this contact, one paid. 25%, observed - not the
    40% the flat per-class rate would assume.
    """
    for i in range(3):
        make(db, f"pay_c{i}", trail=[WA], state="FAILED_STOPPED")
    make(db, "pay_c3", trail=[WA, RECOVERED], state="RECOVERED")
    record = make(db, "pay_now")

    bp, source, basis = erv.estimate_probability(db, record, "whatsapp_link")

    assert source == erv.ProbabilitySource.CUSTOMER_HISTORY
    assert bp == 2500
    assert "1 of 4" in basis


def test_a_customer_who_has_never_paid_gets_a_zero_probability(db):
    for i in range(4):
        make(db, f"pay_never{i}", trail=[WA], state="FAILED_STOPPED")
    record = make(db, "pay_now")

    bp, source, _ = erv.estimate_probability(db, record, "whatsapp_link")

    assert source == erv.ProbabilitySource.CUSTOMER_HISTORY
    assert bp == 0


def test_too_little_customer_history_falls_through_to_the_channel(db):
    """
    Two attempts is not a rate. Rather than let one customer's coin-flip drive
    a spend decision, it falls through to the wider evidence.
    """
    make(db, "pay_thin1", trail=[WA], state="FAILED_STOPPED")
    make(db, "pay_thin2", trail=[WA], state="FAILED_STOPPED")
    for i in range(20):
        make(db, f"pay_other{i}", phone=f"+9198000000{i:02d}",
             trail=[WA, RECOVERED] if i < 5 else [WA],
             state="RECOVERED" if i < 5 else "FAILED_STOPPED")
    record = make(db, "pay_now")

    bp, source, basis = erv.estimate_probability(db, record, "whatsapp_link")

    assert source == erv.ProbabilitySource.CHANNEL_HISTORY
    assert bp == 2272                       # 5 of 22 attempts, floored
    assert "5 of 22" in basis


def test_with_no_history_at_all_the_labelled_default_is_used(db):
    record = make(db, "pay_new")

    bp, source, basis = erv.estimate_probability(db, record, "whatsapp_link")

    assert source == erv.ProbabilitySource.DEFAULT_ESTIMATE
    assert bp == int(RECOVERY_RATES["AUTH_FRICTION"] * 10_000)
    assert "estimate" in basis.lower()
    assert "not observed" in basis.lower()


def test_the_source_is_always_labelled_and_always_one_of_three(db):
    record = make(db, "pay_label")

    estimate = erv.evaluate(db, record, "whatsapp_link", 50)

    assert estimate.probability_source in (
        erv.ProbabilitySource.CUSTOMER_HISTORY,
        erv.ProbabilitySource.CHANNEL_HISTORY,
        erv.ProbabilitySource.DEFAULT_ESTIMATE,
    )
    assert estimate.probability_basis
    assert estimate.observed is False        # a default is not an observation


def test_an_observed_probability_is_marked_as_observed(db):
    for i in range(3):
        make(db, f"pay_obs{i}", trail=[WA, RECOVERED], state="RECOVERED")
    record = make(db, "pay_now")

    assert erv.evaluate(db, record, "whatsapp_link", 50).observed is True


def test_an_unclassified_record_gets_a_zero_default_rather_than_a_guess(db):
    record = make(db, "pay_unclassified", failure_class=None)

    bp, source, _ = erv.estimate_probability(db, record, "whatsapp_link")

    assert source == erv.ProbabilitySource.DEFAULT_ESTIMATE
    assert bp == 0


def test_the_channel_statistics_notice_an_outcome_that_lands_mid_session(db):
    """
    The channel-wide stats are memoized on the session and keyed on the ledger
    head, because a 65-record batch would otherwise walk the whole chain 65
    times. The key is what makes that safe: the ledger is append-only, so while
    the head is unchanged nothing already counted can have changed - and the
    moment an outcome lands, the head moves and the cache must not be reused.

    Without the key this is a session that never learns anything after its
    first question, which is the worst of both designs: the cost of reading
    history and none of the benefit.
    """
    for i in range(20):
        make(db, f"pay_base{i}", phone=f"+9198100000{i:02d}", trail=[WA],
             state="FAILED_STOPPED")
    record = make(db, "pay_watch")

    before, source, _ = erv.estimate_probability(db, record, "whatsapp_link")
    assert source == erv.ProbabilitySource.CHANNEL_HISTORY
    assert before == 0

    for i in range(10):
        make(db, f"pay_win{i}", phone=f"+9198200000{i:02d}",
             trail=[WA, RECOVERED], state="RECOVERED")

    after, _, basis = erv.estimate_probability(db, record, "whatsapp_link")

    assert after == 10 * 10_000 // 30          # 10 of 30 attempts
    assert "10 of 30" in basis


def test_the_same_inputs_always_produce_the_same_estimate(db):
    for i in range(3):
        make(db, f"pay_d{i}", trail=[WA, RECOVERED], state="RECOVERED")
    record = make(db, "pay_now")

    assert erv.evaluate(db, record, "whatsapp_link", 50).to_dict() == \
        erv.evaluate(db, record, "whatsapp_link", 50).to_dict()


# =============================================================================
# The trace
# =============================================================================


def test_the_trace_matches_the_documented_format_line_for_line(db):
    """
    The worked example as it appears in README.md and documentation/, checked
    line for line so the two cannot drift apart.

    The cost is read from config rather than written in, because that is the
    number the example got wrong once already: a WhatsApp send costs 50 *paise*,
    not Rs 50, and an example quoting a figure a hundred times the real one
    teaches a reviewer to distrust every other number beside it.
    """
    record = make(db, "pay_spec", amount=500_000)
    cost = CHANNEL_COSTS_PAISE["AUTH_FRICTION"]

    lines = erv.trace_lines(erv.evaluate(db, record, "whatsapp_link", cost,
                                         probability_bp=6200))

    assert cost == 50                                   # paise, not rupees
    assert lines[0] == "Payment: Rs 5,000.00"
    assert lines[1] == "Action: WhatsApp Link"
    assert lines[2].startswith("Estimated success: 62%")
    assert lines[3] == "Expected recovery: Rs 3,100.00"
    assert lines[4] == "Cost: Rs 0.50"
    assert lines[5] == "Expected net: Rs 3,099.50"
    assert lines[6] == "Decision: PROCEED"


def test_an_assumed_probability_is_marked_as_such_in_the_trace(db):
    """
    The one deliberate departure from the requested format. "62%" reads as a
    measurement; when it is the config default rather than anything observed,
    the line has to say so, or the trace overstates what this system knows.
    """
    record = make(db, "pay_assumed", amount=500_000)

    assumed = erv.trace_lines(erv.evaluate(db, record, "whatsapp_link", 50))

    for i in range(3):
        make(db, f"pay_seen{i}", trail=[WA, RECOVERED], state="RECOVERED")
    observed = erv.trace_lines(erv.evaluate(db, record, "whatsapp_link", 50))

    assert any("(default estimate)" in l for l in assumed)
    assert not any("(default estimate)" in l for l in observed)


def test_a_rejected_action_says_why_in_the_trace(db):
    record = make(db, "pay_trace_stop", amount=5_000)

    lines = erv.trace_lines(erv.evaluate(db, record, "whatsapp_link", 50,
                                         probability_bp=80))

    assert "Expected net: -Rs 0.10" in lines
    assert "Decision: STOP - ECONOMICALLY UNVIABLE" in lines


# =============================================================================
# Policy integration
# =============================================================================


def test_a_profitable_action_proceeds_and_carries_its_working(db):
    record = make(db, "pay_go", amount=500_000)

    decision = decide_next_action(db, record)

    assert decision.should_act is True
    assert decision.reason_code == ReasonCode.PROCEED
    assert decision.erv["viable"] is True
    assert "Expected net:" in decision.reason


def test_a_customer_who_never_pays_stops_the_next_message(db):
    """
    The case the flat per-class rate cannot see. Four links to this contact,
    none paid, so the observed probability is zero and a fifth is worth less
    than the 50 paise it costs. Every other gate passed.
    """
    for i in range(4):
        make(db, f"pay_dead{i}", trail=[WA], state="FAILED_STOPPED")
    record = make(db, "pay_next", amount=500_000)

    decision = decide_next_action(db, record)

    assert decision.should_act is False
    assert decision.reason_code == ReasonCode.ECONOMICALLY_UNVIABLE
    assert decision.erv["expected_net_paise"] == -50
    assert "STOP - ECONOMICALLY UNVIABLE" in decision.reason


@pytest.mark.asyncio
async def test_an_unviable_action_sends_nothing_and_spends_nothing(db):
    for i in range(4):
        make(db, f"pay_dead{i}", trail=[WA], state="FAILED_STOPPED")
    record = make(db, "pay_next", amount=500_000)

    result = await recovery_actions.execute_recovery(db, record, source=LIVE_SOURCE)
    trail = actions(db, "pay_next")

    assert result["action"] == "declined"
    assert result["reason_code"] == ReasonCode.ECONOMICALLY_UNVIABLE
    assert WA not in trail
    assert f"POLICY_DECLINED_{ReasonCode.ECONOMICALLY_UNVIABLE}" in trail
    assert db.query(RazorpayPaymentLink).count() == 0
    assert sum(e.cost_paise or 0 for e in db.query(AuditTrailEntry)
               .filter(AuditTrailEntry.payment_id == "pay_next")) == 0


def test_the_erv_block_is_attached_even_when_erv_is_not_what_refused(db):
    """
    A reviewer reading any refusal should be able to see the economics that
    were not the reason, rather than having to infer them.
    """
    record = make(db, "pay_hard", failure_class="MANDATE_BALANCE",
                  error_reason="card_expired")
    ledger.append_entry(db, payment_id=record.payment_id, batch_id=None,
                        action=WA, actor="system", details="x", cost_paise=50)
    ledger.append_entry(db, payment_id=record.payment_id, batch_id=None,
                        action=WA, actor="system", details="x", cost_paise=50)

    decision = decide_next_action(db, record)

    assert decision.should_act is False
    assert decision.reason_code != ReasonCode.ECONOMICALLY_UNVIABLE
    assert decision.erv is None      # no channel was chosen, so nothing to value


# --- Existing refusals still win --------------------------------------------


@pytest.mark.parametrize("setup,expected", [
    ("hard_decline", ReasonCode.HARD_DECLINE),
    ("holdout", ReasonCode.HOLDOUT_CONTROL),
    ("retry_cap", ReasonCode.RETRY_CAP_REACHED),
    ("ladder_done", ReasonCode.LADDER_EXHAUSTED),
    ("cac", ReasonCode.CAC_CEILING),
    ("margin", ReasonCode.NEGATIVE_EXPECTED_VALUE),
])
def test_every_existing_refusal_still_wins_over_erv(db, setup, expected):
    """
    ERV runs last on purpose. A compliance halt, a spend ceiling or an
    exhausted ladder must never be reported as an economic stop - the reason
    code is what an operator acts on, and the most fundamental one has to be
    the one that survives.
    """
    holdout = False
    if setup == "hard_decline":
        record = make(db, "pay_x", failure_class="HARD_DECLINE",
                      error_reason="compliance_violation")
    elif setup == "holdout":
        record = make(db, "pay_x")
        holdout = True
    elif setup == "retry_cap":
        record = make(db, "pay_x", failure_class="TRANSIENT_TECHNICAL",
                      error_reason="bank_technical_error",
                      trail=["RETRY_SILENT_ATTEMPT"] * 3)
    elif setup == "ladder_done":
        record = make(db, "pay_x", trail=[WA, WA])
    elif setup == "cac":
        # 15% of Rs 3 is 45p; one 50p send breaches it.
        record = make(db, "pay_x", amount=300)
    else:
        # Margin check: cost 50p against 40% x 20% margin on Rs 5 = 40p.
        record = make(db, "pay_x", amount=500)

    decision = decide_next_action(db, record, is_holdout=holdout)

    assert decision.should_act is False
    assert decision.reason_code == expected


def test_consent_withdrawal_is_never_reported_as_an_economic_stop(db):
    from app.consent import record_opt_out

    for i in range(4):
        make(db, f"pay_dead{i}", trail=[WA], state="FAILED_STOPPED")
    record = make(db, "pay_optout", amount=500_000)
    record_opt_out(db, phone=PHONE, source="test", payment_id="pay_optout",
                   channel="all", batch_id=None)

    decision = decide_next_action(db, record)

    assert decision.reason_code == ReasonCode.CONSENT_WITHDRAWN


# --- The guard still runs afterwards ----------------------------------------


@pytest.mark.asyncio
async def test_the_safety_guard_still_refuses_an_action_erv_approved(db):
    """
    ERV approving an attempt is not authorisation. A live record whose error
    code nobody has approved for automation is still blocked, after policy and
    ERV have both said yes.
    """
    record = make(db, "pay_unmapped", amount=500_000,
                  error_reason="psp_handle_unreachable")

    decision = decide_next_action(db, record)
    result = await recovery_actions.execute_recovery(db, record, source=LIVE_SOURCE)

    assert decision.should_act is True
    assert decision.erv["viable"] is True
    assert result["action"] == "declined"
    assert "SAFETY_GUARD_BLOCKED" in actions(db, "pay_unmapped")
    assert WA not in actions(db, "pay_unmapped")


def test_the_guard_still_only_accepts_a_real_policy_decision(db):
    """ERV rides on PolicyDecision; it must not become a second way in."""
    from app import safety_guard

    record = make(db, "pay_guard")
    estimate = erv.evaluate(db, record, "whatsapp_link", 50, probability_bp=9000)

    verdict = safety_guard.authorize(db, record, estimate, source=LIVE_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == safety_guard.GuardCode.NOT_A_POLICY_DECISION


# =============================================================================
# Nothing else moved
# =============================================================================


def test_no_new_fsm_state():
    assert set(VALID_TRANSITIONS) == {
        "INGESTED", "DIAGNOSED", "INTERVENING", "RECOVERED", "FAILED_STOPPED"}


def test_no_new_table_was_added():
    assert "expected_recovery" not in " ".join(Base.metadata.tables)
    assert set(Base.metadata.tables) == {
        "payment_failure_records", "audit_trail_entries", "batch_runs",
        "consent_records", "razorpay_payment_links", "recovery_attempt_claims",
    }


def test_the_erv_module_imports_nothing_that_can_act():
    import ast

    import app.erv as module

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


@pytest.mark.asyncio
async def test_a_synthetic_ladder_runs_exactly_as_it_did(db):
    """
    The demo path. At the seeded dataset's smallest amount, no rung is close to
    unviable, so ERV approves everything and the run is what it always was:
    two sends, 100 paise, stopped when the ladder ran out.
    """
    record = make(db, "pay_synth", amount=SMALLEST_SYNTHETIC_AMOUNT,
                  source=SYNTHETIC_SOURCE, batch_id="batch_erv")

    outcomes = []
    while record.recovery_state not in ("RECOVERED", "FAILED_STOPPED"):
        result = await recovery_actions.execute_recovery(db, record,
                                                         source=SYNTHETIC_SOURCE)
        outcomes.append(result["action"])
        if result["action"] in ("declined", "no_action"):
            break

    assert outcomes == ["whatsapp_link", "whatsapp_link", "declined"]
    assert sum(e.cost_paise or 0 for e in db.query(AuditTrailEntry)) == 100
    assert ReasonCode.ECONOMICALLY_UNVIABLE not in " ".join(actions(db, "pay_synth"))


def test_erv_cannot_bind_at_any_amount_the_seeded_dataset_contains(db):
    """
    Stated as an inequality rather than left to a demo run. With the default
    per-class rates, the cheapest rung that could be refused would need an
    amount two orders of magnitude below anything in the batch.
    """
    for failure_class, rate in RECOVERY_RATES.items():
        if rate == 0:
            continue
        cost = max(CHANNEL_COSTS_PAISE.values())
        expected = SMALLEST_SYNTHETIC_AMOUNT * int(rate * 10_000) // 10_000
        assert expected - cost > 0, failure_class


@pytest.mark.asyncio
async def test_duplicate_execution_is_still_exactly_once_with_erv_in_the_path(db):
    """
    ERV sits before the claim, so a second worker reaching it must still be
    stopped by the claim rather than by arithmetic that happens to agree.
    """
    import asyncio

    engine = db.get_bind()
    other = sessionmaker(bind=engine, expire_on_commit=False)()
    record = make(db, "pay_dupe", amount=500_000)
    mirror = other.query(PaymentFailureRecord).filter_by(payment_id="pay_dupe").one()

    started, release = asyncio.Event(), asyncio.Event()
    real = recovery_actions.CHANNEL_ACTION_MAP["whatsapp_link"]

    async def held(session, rec, source=None):
        started.set()
        await release.wait()
        return await real(session, rec, source=source)

    recovery_actions.CHANNEL_ACTION_MAP["whatsapp_link"] = held
    try:
        async def follower():
            await asyncio.wait_for(started.wait(), timeout=5)
            try:
                return await asyncio.wait_for(
                    recovery_actions.execute_recovery(other, mirror,
                                                      source=LIVE_SOURCE), timeout=5)
            finally:
                release.set()

        first, second = await asyncio.gather(
            recovery_actions.execute_recovery(db, record, source=LIVE_SOURCE),
            follower())
    finally:
        recovery_actions.CHANNEL_ACTION_MAP["whatsapp_link"] = real
        other.close()

    assert first["action"] == "whatsapp_link"
    assert second["action"] == "no_action"
    assert actions(db, "pay_dupe").count(WA) == 1


@pytest.mark.asyncio
async def test_the_dashboard_economics_are_unaffected(db, monkeypatch):
    from app.routes import metrics as metrics_route

    record = make(db, "pay_metrics", amount=500_000, batch_id="batch_erv",
                  source=SYNTHETIC_SOURCE)
    await recovery_actions.execute_recovery(db, record, source=SYNTHETIC_SOURCE)

    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: db)
    result = await metrics_route.get_dashboard_metrics(scope="batch",
                                                       batch_id="batch_erv")

    assert result["total_channel_cost_paise"] == 50
    assert result["interventions"]["whatsapp_link"]["attempts"] == 1
    assert result["intervention_summary"]["cohort_cost_paise"] == 50


def test_nothing_here_reaches_an_external_api(db):
    from app import llm_cache, voice_pipeline

    record = make(db, "pay_net", amount=500_000)
    erv.evaluate(db, record, "whatsapp_link", 50)

    assert llm_cache.DEMO_MODE is True
    assert voice_pipeline.DEMO_MODE is True
    assert db.query(RazorpayPaymentLink).count() == 0
