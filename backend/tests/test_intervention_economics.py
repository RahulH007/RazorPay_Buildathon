"""
Recovery economics, per intervention.

The dashboard could already say how much money came back. It could not say
which action brought it back, and that is the question a merchant asks second:
of silent retry, a WhatsApp link, a UPI resequence, a Hinglish voice call and
a human handoff, which ones pay for themselves?

Nothing new is recorded to answer it. Every attempt is already a ledger entry
carrying its own cost in paise, and every recovery is already a state
transition on the same chain, so the attribution is a read over data that has
been there since the first batch ran. The rule is deliberately narrow:

    a recovery is credited to the last attempt made before the record
    transitioned to RECOVERED - and to nothing at all when no attempt
    preceded it

That second half is the part worth testing hardest. The control arm is never
contacted and some of it recovers anyway; a system that quietly handed those
rupees to whichever channel happened to be nearby would report a return it did
not earn. Those recoveries are counted, reported, and attributed to no
intervention.

Scoping matches the cohort scoping one layer up, batch id and all, because the
ledger is append-only: a re-run adds entries against the same payment ids, and
an attribution keyed on payment id alone would sum every run ever performed.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app import ledger, settlement
from app.config import CHANNEL_COSTS_PAISE
from app.guardrails import ATTEMPT_ACTIONS
from app.intervention_economics import (
    INTERVENTION_BY_ACTION,
    RECOVERY_TRANSITION_ACTIONS,
    by_intervention,
)
from app.models import PaymentFailureRecord
from app.policy import ATTEMPT_LADDER, CHANNEL_ACTION_COST_PAISE
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.routes import metrics as metrics_route
from app.state_machine import VALID_TRANSITIONS

BATCH = "batch_intervention_test"

SYNTH_AMOUNT = 100_000      # Rs 1,000
LIVE_AMOUNT = 45_000        # Rs 450

WA_COST = CHANNEL_COSTS_PAISE["AUTH_FRICTION"]           # 50p
UPI_COST = CHANNEL_COSTS_PAISE["MANDATE_BALANCE"]        # 50p
VOICE_COST = CHANNEL_COSTS_PAISE["B2B_RECEIVABLE"]       # 200p
RETRY_COST = CHANNEL_COSTS_PAISE["TRANSIENT_TECHNICAL"]  # 0p

WA_SENT = "WHATSAPP_LINK_SENT"
UPI_SENT = "MANDATE_RESEQUENCED"
VOICE_SENT = "VOICE_CALL_INITIATED"
RETRY_SENT = "RETRY_SILENT_ATTEMPT"
HUMAN = "ESCALATED_TO_HUMAN"
RECOVERED_FROM_INTERVENING = "STATE_INTERVENING_TO_RECOVERED"
RECOVERED_FROM_DIAGNOSED = "STATE_DIAGNOSED_TO_RECOVERED"

COST_BY_ACTION = {
    WA_SENT: WA_COST,
    UPI_SENT: UPI_COST,
    VOICE_SENT: VOICE_COST,
    RETRY_SENT: RETRY_COST,
    HUMAN: 0,
}


# --- Fixture ----------------------------------------------------------------


def _build(db, payment_record, payment_id, amount, state, trail,
           source=SYNTHETIC_SOURCE, batch_id=BATCH, arm="treated",
           failure_class="AUTH_FRICTION"):
    """
    One record plus its ledger trail, appended in the order given.

    `trail` is a list of action names. Sequence numbers come from the ledger
    itself, so the order written here is the order the attribution walks.
    """
    record = payment_record(
        payment_id=payment_id,
        amount=amount,
        failure_class=failure_class,
        recovery_state=state,
        error_reason="authentication_failed",
        source=source,
        batch_id=batch_id,
        arm=arm,
    )
    db.add(record)
    db.commit()

    for action in trail:
        ledger.append_entry(
            db, payment_id=payment_id, batch_id=batch_id,
            action=action, actor="system", details="intervention fixture",
            cost_paise=COST_BY_ACTION.get(action, 0),
        )
    return record


@pytest.fixture
def ladder(db_session, payment_record):
    """
    A population where every attribution rule has at least one witness, and
    where no two channels share an outcome - so a reading that mixed them up
    could not land on the right number by accident.

        pay_wa_won       whatsapp once, recovered            Rs 1,000
        pay_wa_lost      whatsapp twice, stopped
        pay_voice_won    whatsapp then voice, recovered      Rs 1,000
        pay_retry_won    silent retry once, recovered        Rs 1,000
        pay_upi_won      upi resequence once, recovered      Rs 1,000
        pay_control_won  never contacted, recovered anyway   Rs 1,000
        pay_human        whatsapp, voice, handoff, still open
        pay_hard         hard decline, never contacted, stopped
        pay_live_won     whatsapp once, recovered            Rs 450
        pay_live_open    whatsapp once, still open
    """
    _build(db_session, payment_record, "pay_wa_won", SYNTH_AMOUNT, "RECOVERED",
           [WA_SENT, RECOVERED_FROM_INTERVENING])
    _build(db_session, payment_record, "pay_wa_lost", SYNTH_AMOUNT,
           "FAILED_STOPPED", [WA_SENT, WA_SENT])
    _build(db_session, payment_record, "pay_voice_won", SYNTH_AMOUNT,
           "RECOVERED", [WA_SENT, VOICE_SENT, RECOVERED_FROM_INTERVENING],
           failure_class="B2B_RECEIVABLE")
    _build(db_session, payment_record, "pay_retry_won", SYNTH_AMOUNT,
           "RECOVERED", [RETRY_SENT, RECOVERED_FROM_INTERVENING],
           failure_class="TRANSIENT_TECHNICAL")
    _build(db_session, payment_record, "pay_upi_won", SYNTH_AMOUNT, "RECOVERED",
           [UPI_SENT, RECOVERED_FROM_INTERVENING],
           failure_class="MANDATE_BALANCE")
    _build(db_session, payment_record, "pay_control_won", SYNTH_AMOUNT,
           "RECOVERED", [RECOVERED_FROM_DIAGNOSED], arm="control")
    _build(db_session, payment_record, "pay_human", SYNTH_AMOUNT, "INTERVENING",
           [WA_SENT, VOICE_SENT, HUMAN], failure_class="B2B_RECEIVABLE")
    _build(db_session, payment_record, "pay_hard", SYNTH_AMOUNT,
           "FAILED_STOPPED", [], failure_class="HARD_DECLINE")

    _build(db_session, payment_record, "pay_live_won", LIVE_AMOUNT, "RECOVERED",
           [WA_SENT, RECOVERED_FROM_INTERVENING],
           source=LIVE_SOURCE, batch_id=None, arm=None)
    _build(db_session, payment_record, "pay_live_open", LIVE_AMOUNT,
           "INTERVENING", [WA_SENT],
           source=LIVE_SOURCE, batch_id=None, arm=None)

    return db_session


def batch_records(db):
    return db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.batch_id == BATCH).all()


def live_records(db):
    return db.query(PaymentFailureRecord).filter(
        PaymentFailureRecord.source == LIVE_SOURCE).all()


def all_records(db):
    return db.query(PaymentFailureRecord).all()


# --- Attribution ------------------------------------------------------------


def test_every_intervention_is_named_by_its_own_channel(ladder):
    """The rows are the policy engine's channels, not a parallel vocabulary."""
    report = by_intervention(ladder, batch_records(ladder))

    assert set(report["interventions"]) == {
        "whatsapp_link", "hinglish_voice", "silent_retry",
        "upi_resequence", "human_queue",
    }


def test_attempts_count_every_action_and_records_count_every_customer(ladder):
    """
    Two sends to one customer cost twice and are two attempts, but the channel
    has still only touched one record. Both numbers are reported, because a
    rate over the wrong one is the easiest way to flatter a channel that
    needed a second try.
    """
    whatsapp = by_intervention(
        ladder, batch_records(ladder))["interventions"]["whatsapp_link"]

    # pay_wa_won 1, pay_wa_lost 2, pay_voice_won 1, pay_human 1
    assert whatsapp["attempts"] == 5
    assert whatsapp["records"] == 4


def test_a_recovery_is_credited_to_the_last_attempt_before_it(ladder):
    """
    pay_voice_won was sent a WhatsApp link, escalated to a voice call, then
    paid. The voice call is what closed it. Crediting the first rung, or
    crediting both, would make the cheap channel look like it earned money the
    expensive one had to go and fetch.
    """
    interventions = by_intervention(
        ladder, batch_records(ladder))["interventions"]

    assert interventions["hinglish_voice"]["recovered"] == 1
    assert interventions["hinglish_voice"]["recovered_gmv_paise"] == SYNTH_AMOUNT
    # whatsapp touched pay_voice_won too, and is credited with none of it.
    assert interventions["whatsapp_link"]["recovered"] == 1
    assert interventions["whatsapp_link"]["recovered_gmv_paise"] == SYNTH_AMOUNT


def test_an_attempt_after_the_recovery_earns_no_credit(db_session, payment_record):
    """
    The cutoff is the recovery itself, not the end of the trail. An entry
    written after the record settled cannot have caused the settlement, and
    reading the last attempt overall would hand it the money.
    """
    _build(db_session, payment_record, "pay_late", SYNTH_AMOUNT, "RECOVERED",
           [WA_SENT, RECOVERED_FROM_INTERVENING, VOICE_SENT])

    interventions = by_intervention(
        db_session, batch_records(db_session))["interventions"]

    assert interventions["whatsapp_link"]["recovered"] == 1
    assert interventions["hinglish_voice"]["attempts"] == 1
    assert interventions["hinglish_voice"]["recovered"] == 0
    assert interventions["hinglish_voice"]["recovered_gmv_paise"] == 0


def test_a_recovery_with_no_attempt_is_attributed_to_nothing(ladder):
    """
    The control arm is never contacted and some of it pays anyway. Those rupees
    are real and are reported, but they belong to no intervention - which is
    the whole point of holding an arm out in the first place.
    """
    report = by_intervention(ladder, batch_records(ladder))

    assert report["summary"]["unattributed_recovered"] == 1
    assert report["summary"]["unattributed_recovered_gmv_paise"] == SYNTH_AMOUNT
    assert sum(i["recovered"] for i in report["interventions"].values()) == 4


def test_a_record_that_was_never_acted_on_appears_in_no_channel(ladder):
    """
    A hard decline is never contacted, and neither is the control arm. Measured
    on their own they produce no rows at all - the recovery among them is still
    counted, and still credited to nobody.
    """
    untouched = [r for r in batch_records(ladder)
                 if r.payment_id in ("pay_hard", "pay_control_won")]

    report = by_intervention(ladder, untouched)

    assert report["interventions"] == {}
    assert report["summary"]["attributed_cost_paise"] == 0
    assert report["summary"]["cohort_cost_paise"] == 0
    assert report["summary"]["unattributed_recovered"] == 1


# --- Cost -------------------------------------------------------------------


def test_cost_is_the_ledger_cost_of_that_channels_own_entries(ladder):
    interventions = by_intervention(
        ladder, batch_records(ladder))["interventions"]

    assert interventions["whatsapp_link"]["cost_paise"] == 5 * WA_COST       # 250p
    assert interventions["hinglish_voice"]["cost_paise"] == 2 * VOICE_COST   # 400p
    assert interventions["upi_resequence"]["cost_paise"] == UPI_COST         # 50p
    assert interventions["silent_retry"]["cost_paise"] == 0
    assert interventions["human_queue"]["cost_paise"] == 0


def test_the_channel_costs_add_up_to_the_cohorts_total_spend(ladder):
    """
    The reconciliation that makes the table trustworthy. The per-channel figure
    and the headline figure come from two independent walks of the ledger, so
    their agreement is evidence rather than a tautology - and any spend the
    table cannot explain is reported rather than dropped.
    """
    records = batch_records(ladder)
    report = by_intervention(ladder, records)

    assert report["summary"]["cohort_cost_paise"] == \
        metrics_route._cohort_cost_paise(ladder, records)
    assert report["summary"]["attributed_cost_paise"] == \
        report["summary"]["cohort_cost_paise"]
    assert report["summary"]["unattributed_cost_paise"] == 0


def test_the_channel_revenue_adds_up_to_the_cohorts_recovered_gmv(ladder):
    records = batch_records(ladder)
    report = by_intervention(ladder, records)

    attributed = sum(i["recovered_gmv_paise"]
                     for i in report["interventions"].values())
    recovered_gmv = sum(r.amount for r in records
                        if r.recovery_state == "RECOVERED")

    assert attributed + report["summary"]["unattributed_recovered_gmv_paise"] \
        == recovered_gmv


# --- Rates and returns ------------------------------------------------------


def test_recovery_rate_is_recovered_over_records_touched(ladder):
    """
    Per record, which is what recovery_rate means everywhere else in this API.
    whatsapp touched four records and won one of them.
    """
    interventions = by_intervention(
        ladder, batch_records(ladder))["interventions"]

    assert interventions["whatsapp_link"]["recovery_rate"] == 25.0
    assert interventions["hinglish_voice"]["recovery_rate"] == 50.0    # 1 of 2
    assert interventions["silent_retry"]["recovery_rate"] == 100.0
    assert interventions["human_queue"]["recovery_rate"] == 0.0


def test_net_recovery_is_revenue_minus_the_spend_that_produced_it(ladder):
    interventions = by_intervention(
        ladder, batch_records(ladder))["interventions"]

    assert interventions["whatsapp_link"]["net_recovery_paise"] == SYNTH_AMOUNT - 250
    assert interventions["hinglish_voice"]["net_recovery_paise"] == SYNTH_AMOUNT - 400
    assert interventions["human_queue"]["net_recovery_paise"] == 0


def test_roi_is_net_over_cost_and_is_omitted_where_it_is_meaningless(ladder):
    """
    A free channel has no return on investment, only a return. Reporting an
    infinite or a zero ROI for silent retry would put a made-up number next to
    four real ones.
    """
    interventions = by_intervention(
        ladder, batch_records(ladder))["interventions"]

    assert interventions["whatsapp_link"]["roi"] == round((SYNTH_AMOUNT - 250) / 250, 2)
    assert interventions["hinglish_voice"]["roi"] == round((SYNTH_AMOUNT - 400) / 400, 2)
    assert interventions["silent_retry"]["roi"] is None
    assert interventions["human_queue"]["roi"] is None


def test_average_recovered_is_reported_per_winning_record(ladder):
    interventions = by_intervention(
        ladder, batch_records(ladder))["interventions"]

    assert interventions["whatsapp_link"]["average_recovered_paise"] == SYNTH_AMOUNT
    assert interventions["human_queue"]["average_recovered_paise"] == 0


def test_rupee_mirrors_match_the_paise_they_render(ladder):
    for row in by_intervention(
            ladder, batch_records(ladder))["interventions"].values():
        assert row["cost"] == row["cost_paise"] / 100.0
        assert row["recovered_gmv"] == row["recovered_gmv_paise"] / 100.0
        assert row["net_recovery"] == row["net_recovery_paise"] / 100.0


# --- Ranking ----------------------------------------------------------------


def test_the_strongest_intervention_is_the_one_that_nets_the_most(ladder):
    report = by_intervention(ladder, batch_records(ladder))

    # silent_retry recovered Rs 1,000 and spent nothing, so it nets more than
    # upi (Rs 1,000 - 50p), whatsapp (- 250p) or voice (- 400p).
    assert report["summary"]["strongest"] == "silent_retry"
    assert list(report["interventions"]) == [
        "silent_retry", "upi_resequence", "whatsapp_link",
        "hinglish_voice", "human_queue",
    ]


def test_a_channel_that_recovered_nothing_is_never_the_strongest(
        db_session, payment_record):
    """
    With nothing recovered every net is zero or negative, and the cheapest
    channel would win by default. "Strongest" has to mean "won the most money",
    not "lost the least".
    """
    _build(db_session, payment_record, "pay_none", SYNTH_AMOUNT, "INTERVENING",
           [WA_SENT, RETRY_SENT])

    report = by_intervention(db_session, batch_records(db_session))

    assert report["interventions"]["silent_retry"]["net_recovery_paise"] == 0
    assert report["summary"]["strongest"] is None


def test_channels_that_tie_are_ordered_by_name_so_the_table_cannot_flap(
        db_session, payment_record):
    """
    Two free channels, one recovery each: identical on every figure the ranking
    reads. Something has to break the tie deterministically, or the same
    database renders in a different order on the next page load.
    """
    _build(db_session, payment_record, "pay_a", SYNTH_AMOUNT, "RECOVERED",
           [RETRY_SENT, RECOVERED_FROM_INTERVENING])
    _build(db_session, payment_record, "pay_b", SYNTH_AMOUNT, "RECOVERED",
           [HUMAN, RECOVERED_FROM_INTERVENING])

    report = by_intervention(db_session, batch_records(db_session))

    assert report["interventions"]["human_queue"]["net_recovery_paise"] == \
        report["interventions"]["silent_retry"]["net_recovery_paise"]
    assert list(report["interventions"]) == ["human_queue", "silent_retry"]
    assert report["summary"]["strongest"] == "human_queue"


# --- Cohort isolation -------------------------------------------------------


def test_the_batch_cohort_sees_none_of_the_live_traffic(ladder):
    report = by_intervention(ladder, batch_records(ladder))

    # The live records were sent WhatsApp links too; none of that is in here.
    assert report["interventions"]["whatsapp_link"]["attempts"] == 5
    assert report["summary"]["cohort_cost_paise"] == 250 + 400 + 50


def test_the_live_cohort_sees_only_its_own_sends(ladder):
    report = by_intervention(ladder, live_records(ladder))
    whatsapp = report["interventions"]["whatsapp_link"]

    assert set(report["interventions"]) == {"whatsapp_link"}
    assert whatsapp["attempts"] == 2
    assert whatsapp["records"] == 2
    assert whatsapp["recovered"] == 1
    assert whatsapp["recovered_gmv_paise"] == LIVE_AMOUNT
    assert whatsapp["cost_paise"] == 2 * WA_COST


def test_all_is_exactly_the_batch_plus_the_live_traffic(ladder):
    batch = by_intervention(ladder, batch_records(ladder))
    live = by_intervention(ladder, live_records(ladder))
    every = by_intervention(ladder, all_records(ladder))

    assert every["interventions"]["whatsapp_link"]["attempts"] == \
        batch["interventions"]["whatsapp_link"]["attempts"] \
        + live["interventions"]["whatsapp_link"]["attempts"]
    assert every["summary"]["cohort_cost_paise"] == \
        batch["summary"]["cohort_cost_paise"] + live["summary"]["cohort_cost_paise"]
    assert every["summary"]["unattributed_recovered"] == \
        batch["summary"]["unattributed_recovered"] \
        + live["summary"]["unattributed_recovered"]


def test_a_rerun_of_the_same_records_does_not_double_the_spend(ladder):
    """
    The ledger is append-only, so a second run adds entries against the same
    payment ids under a new batch id. Attribution keyed on payment id alone
    would count both runs and make every channel look twice as expensive as it
    is - the same trap the cohort cost query was written to avoid.
    """
    before = by_intervention(
        ladder, batch_records(ladder))["interventions"]["whatsapp_link"]

    for record in batch_records(ladder):
        ledger.append_entry(
            ladder, payment_id=record.payment_id, batch_id="batch_a_later_run",
            action=WA_SENT, actor="system", details="a later run",
            cost_paise=WA_COST,
        )

    after = by_intervention(
        ladder, batch_records(ladder))["interventions"]["whatsapp_link"]

    assert after["attempts"] == before["attempts"]
    assert after["cost_paise"] == before["cost_paise"]


# --- Idempotency ------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_replayed_settlement_does_not_recover_the_same_record_twice(
        db_session, payment_record):
    """
    Settlement is exactly-once, and the attribution has to stay exactly-once
    with it. A duplicate webhook writes no second transition, so the channel
    must not be credited twice - the fastest route to a recovery rate above
    100%.
    """
    _build(db_session, payment_record, "pay_dupe", SYNTH_AMOUNT, "INTERVENING",
           [WA_SENT])

    first = await settlement.handle_payment_captured(db_session, "pay_dupe", {})
    once = by_intervention(db_session, batch_records(db_session))

    second = await settlement.handle_payment_captured(db_session, "pay_dupe", {})
    twice = by_intervention(db_session, batch_records(db_session))

    assert first["status"] == "recovered"
    assert second["status"] == "already_recovered"
    assert once["interventions"]["whatsapp_link"]["recovered"] == 1
    assert twice["interventions"]["whatsapp_link"] == \
        once["interventions"]["whatsapp_link"]


@pytest.mark.asyncio
async def test_a_real_settlement_credits_the_channel_that_preceded_it(
        db_session, payment_record):
    """
    End to end through the real transition rather than a hand-written entry, so
    the action name the attribution keys on is the one state_machine actually
    writes.
    """
    _build(db_session, payment_record, "pay_real", SYNTH_AMOUNT, "INTERVENING",
           [WA_SENT, VOICE_SENT])

    await settlement.handle_payment_captured(db_session, "pay_real", {})
    interventions = by_intervention(
        db_session, batch_records(db_session))["interventions"]

    assert interventions["hinglish_voice"]["recovered"] == 1
    assert interventions["whatsapp_link"]["recovered"] == 0


# --- Empty ------------------------------------------------------------------


def test_an_empty_cohort_reports_an_empty_table_not_an_error(db_session):
    report = by_intervention(db_session, [])

    assert report["interventions"] == {}
    assert report["summary"]["strongest"] is None
    assert report["summary"]["cohort_cost_paise"] == 0
    assert report["summary"]["unattributed_recovered"] == 0


# --- Drift ------------------------------------------------------------------


def test_every_attempt_action_the_guardrails_count_has_an_intervention():
    """
    guardrails.ATTEMPT_ACTIONS is what the retry cap counts. If an action can
    exhaust the ladder it is an intervention, and a new one added there without
    a name here would silently vanish from the economics.
    """
    for action in ATTEMPT_ACTIONS:
        assert action in INTERVENTION_BY_ACTION


def test_every_intervention_is_a_channel_the_policy_engine_can_choose():
    """No parallel vocabulary: these are the ladder's own rung names."""
    ladder_channels = {c for rungs in ATTEMPT_LADDER.values() for c in rungs}

    for channel in INTERVENTION_BY_ACTION.values():
        assert channel in ladder_channels
        assert channel in CHANNEL_ACTION_COST_PAISE


def test_the_recovery_transitions_are_read_off_the_state_machine():
    """
    Derived, not transcribed. A new state that may reach RECOVERED has to be
    picked up here without anyone remembering to, or its recoveries would be
    credited to whatever attempt happened to be last in the trail.
    """
    expected = {
        f"STATE_{state}_TO_RECOVERED"
        for state, allowed in VALID_TRANSITIONS.items()
        if "RECOVERED" in allowed
    }

    assert RECOVERY_TRANSITION_ACTIONS == expected
    assert RECOVERED_FROM_INTERVENING in RECOVERY_TRANSITION_ACTIONS
    assert RECOVERED_FROM_DIAGNOSED in RECOVERY_TRANSITION_ACTIONS


# --- Through the endpoint ---------------------------------------------------


@pytest.fixture
def dashboard(db_session, monkeypatch):
    """The real endpoint, bound to the test session."""
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: db_session)

    async def read(**kwargs):
        return await metrics_route.get_dashboard_metrics(**kwargs)

    return read


@pytest.mark.asyncio
async def test_the_dashboard_reports_the_table_for_the_cohort_it_is_reading(
        ladder, dashboard):
    """
    The table has to describe the same records as the totals it sits under. A
    breakdown of a different population, printed beneath a headline recovery
    rate, is the exact failure the cohort scoping was built to end.
    """
    result = await dashboard(scope="batch", batch_id=BATCH)
    direct = by_intervention(ladder, batch_records(ladder))

    assert result["interventions"] == direct["interventions"]
    assert result["intervention_summary"] == direct["summary"]
    assert result["intervention_summary"]["cohort_cost_paise"] ==         result["total_channel_cost_paise"]


@pytest.mark.asyncio
async def test_the_scopes_report_different_tables(ladder, dashboard):
    batch = await dashboard(scope="batch", batch_id=BATCH)
    live = await dashboard(scope="live")
    every = await dashboard(scope="all")

    assert set(batch["interventions"]) == {
        "whatsapp_link", "hinglish_voice", "silent_retry",
        "upi_resequence", "human_queue",
    }
    assert set(live["interventions"]) == {"whatsapp_link"}
    assert every["interventions"]["whatsapp_link"]["attempts"] ==         batch["interventions"]["whatsapp_link"]["attempts"]         + live["interventions"]["whatsapp_link"]["attempts"]


@pytest.mark.asyncio
async def test_the_recovered_gmv_in_the_table_never_exceeds_the_headline(
        ladder, dashboard):
    """
    Attribution can only divide the money that was actually recovered. If the
    rows ever summed past the headline, some record would have been credited to
    two channels at once.
    """
    for scope in ("batch", "live", "all"):
        result = await dashboard(scope=scope)
        attributed = sum(i["recovered_gmv_paise"]
                         for i in result["interventions"].values())

        assert attributed <= result["recovered_gmv"]
        assert attributed             + result["intervention_summary"]["unattributed_recovered_gmv_paise"]             == result["recovered_gmv"]


@pytest.mark.asyncio
async def test_an_empty_database_reports_an_empty_table(db_session, dashboard):
    result = await dashboard()

    assert result["interventions"] == {}
    assert result["intervention_summary"]["strongest"] is None
    assert result["intervention_summary"]["cohort_cost_paise"] == 0
