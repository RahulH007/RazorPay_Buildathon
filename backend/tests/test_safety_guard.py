"""
The Safety Guard: the final authorization point before any recovery action.

The property under test is a boundary, not a behaviour. event_adapter's
unmapped-reason gate already stops a live webhook carrying an unapproved error
code, and it is tested in tests/test_event_adapter.py and
tests/test_unknown_reason_held.py. Every test here that concerns an unmapped
reason therefore reaches execute_recovery *directly*, bypassing that gate on
purpose: a second layer whose only proof of life is the first layer's test is
not a second layer.

What the guard is claimed to enforce, and what each section below checks:

  * only the deterministic policy engine may authorise an action - an LLM, a
    dict, or a hand-built decision cannot;
  * the channel and the amount come from tables in code, never from the
    proposal;
  * a live error code nobody has approved does not cause an automatic action,
    while the synthetic pipeline that deliberately contains unapproved codes is
    untouched;
  * nothing runs after a payment is settled, or against a record held for a
    person;
  * a refusal is ledgered, costs nothing, moves no state and calls nobody.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest

from app import event_adapter, ledger, razorpay_client, recovery_actions, safety_guard
from app.classifier import RULE_MAP
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.policy import PolicyDecision, ReasonCode
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.safety_guard import GuardCode

BLOCKED = safety_guard.BLOCKED_ACTION
HELD = safety_guard.HELD_FOR_REVIEW_ACTION


# --- Isolation --------------------------------------------------------------


@pytest.fixture(autouse=True)
def never_calls_razorpay(monkeypatch):
    """
    Independent of DEMO_MODE, which is false in this developer's .env.

    These raise rather than no-op, so a guard leak fails loudly instead of
    quietly creating a real Payment Link against live credentials.
    """
    def boom_client(source):
        raise AssertionError(f"Razorpay client built (source={source!r})")

    def boom_link(source, payload):
        raise AssertionError(f"Payment Link creation attempted (source={source!r})")

    monkeypatch.setattr(razorpay_client, "get_client", boom_client)
    monkeypatch.setattr(razorpay_client, "create_payment_link", boom_link)
    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", boom_link)


@pytest.fixture
def offline(monkeypatch):
    """Close the live path, for tests where an action is meant to complete."""
    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: False)


# --- Builders ---------------------------------------------------------------


def live_record(db, **overrides):
    """
    A live record placed straight into DIAGNOSED, bypassing event_adapter.

    That bypass is the point: it puts the record in front of the executor in
    exactly the state a future caller reaching execute_recovery some other way
    would produce.
    """
    values = {
        "payment_id": "pay_guard_live_01",
        "amount": 450000,
        "currency": "INR",
        "method": "card",
        "merchant_id": "acc_LiveMerchant01",
        "customer_name": "Live Customer",
        "customer_phone": "+919876500123",
        "error_reason": "authentication_failed",
        "error_description": "Issuer declined.",
        "failure_class": "AUTH_FRICTION",
        "recovery_state": "DIAGNOSED",
        "source": LIVE_SOURCE,
    }
    values.update(overrides)
    record = PaymentFailureRecord(**values)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def proceed(channel="whatsapp_link", cost_paise=50, attempt_number=0):
    """A PolicyDecision shaped exactly as decide_next_action would return it."""
    return PolicyDecision(
        should_act=True,
        reason_code=ReasonCode.PROCEED,
        reason="test",
        channel=channel,
        attempt_number=attempt_number,
        cost_paise=cost_paise,
    )


def failed_payload(error_reason, payment_id="pay_guard_hook_1", amount=450000):
    return {
        "event": "payment.failed",
        "account_id": "acc_LiveMerchant01",
        "payload": {"payment": {"entity": {
            "id": payment_id,
            "amount": amount,
            "currency": "INR",
            "method": "card",
            "email": "customer@example.com",
            "contact": "+919876500123",
            "error_source": "bank",
            "error_step": "payment_authorization",
            "error_reason": error_reason,
            "error_description": "Something went wrong.",
            "notes": {"customer_name": "Live Customer"},
        }}},
    }


async def ingest(db, payload):
    normalized = event_adapter.normalize_razorpay_payment_failed(payload)
    assert normalized is not None
    return await event_adapter.ingest_and_process(db, normalized)


def actions(db, payment_id=None):
    q = db.query(AuditTrailEntry)
    if payment_id:
        q = q.filter(AuditTrailEntry.payment_id == payment_id)
    return [e.action for e in q.order_by(AuditTrailEntry.sequence_no).all()]


def total_cost(db):
    return sum(e.cost_paise or 0 for e in db.query(AuditTrailEntry).all())


# --- A. A recognised live reason still recovers, exactly as before ----------


@pytest.mark.asyncio
async def test_mapped_live_reason_is_authorized_and_executes(db_session, offline):
    """The guard must not be a blanket refusal. This is the control for the file."""
    assert "authentication_failed" in RULE_MAP

    result = await ingest(db_session, failed_payload("authentication_failed"))
    record = db_session.query(PaymentFailureRecord).one()
    recorded = actions(db_session)

    assert result["status"] == "ingested"
    assert record.failure_class == "AUTH_FRICTION"
    assert record.recovery_state == "INTERVENING"
    assert "WHATSAPP_LINK_SENT" in recorded
    assert BLOCKED not in recorded


def test_authorize_allows_a_well_formed_decision(db_session, payment_record):
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(db_session, record, proceed(),
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is True
    assert verdict.code == GuardCode.ALLOWED


# --- B / C. Unmapped live reasons, with event_adapter's gate bypassed -------


@pytest.mark.parametrize("error_reason", ["payment_failed", "payment_cancelled"])
@pytest.mark.asyncio
async def test_unmapped_live_reason_is_blocked_at_the_executor(
    db_session, error_reason
):
    """
    The exact real-world failure this layer exists for: Razorpay's live
    vocabulary is wider than RULE_MAP, and a bank error string must never
    become an instruction to act.
    """
    assert error_reason not in RULE_MAP
    record = live_record(db_session, error_reason=error_reason)

    result = await recovery_actions.execute_recovery(
        db_session, record, source=LIVE_SOURCE
    )

    assert result["action"] == "declined"
    assert result["reason_code"] == BLOCKED
    assert result["guard_code"] == GuardCode.UNMAPPED_REASON

    recorded = actions(db_session)
    assert BLOCKED in recorded
    # Nothing was sent, created, transitioned or spent.
    assert "WHATSAPP_LINK_SENT" not in recorded
    assert "RETRY_SILENT_ATTEMPT" not in recorded
    assert "MANDATE_RESEQUENCED" not in recorded
    assert "VOICE_CALL_INITIATED" not in recorded
    assert not any(a.startswith("STATE_") for a in recorded)
    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert total_cost(db_session) == 0
    assert record.recovery_state == "DIAGNOSED"


@pytest.mark.parametrize("error_reason", ["payment_failed", "payment_cancelled"])
def test_unmapped_live_reason_refused_by_authorize(db_session, error_reason):
    record = live_record(db_session, error_reason=error_reason)

    verdict = safety_guard.authorize(db_session, record, proceed(), source=LIVE_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.UNMAPPED_REASON
    assert "RULE_MAP" in verdict.reason


@pytest.mark.asyncio
async def test_guard_still_blocks_when_the_live_path_is_wide_open(
    db_session, monkeypatch
):
    """
    With is_configured forced true, a leak would reach create_payment_link and
    the autouse fixture would raise. The guard must refuse before that.
    """
    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: True)
    record = live_record(db_session, error_reason="payment_cancelled")

    result = await recovery_actions.execute_recovery(
        db_session, record, source=LIVE_SOURCE
    )

    assert result["guard_code"] == GuardCode.UNMAPPED_REASON
    assert db_session.query(RazorpayPaymentLink).count() == 0


# --- D. Only the policy engine may authorise --------------------------------


@pytest.mark.parametrize("proposal", [
    pytest.param({"should_act": True, "channel": "whatsapp_link",
                  "cost_paise": 50, "reason_code": "PROCEED"}, id="dict"),
    pytest.param(None, id="none"),
    pytest.param("send_whatsapp_link", id="string"),
    pytest.param(
        type("FakeDecision", (), {"should_act": True, "channel": "whatsapp_link",
                                  "cost_paise": 50, "attempt_number": 0,
                                  "reason_code": "PROCEED"})(),
        id="lookalike-object",
    ),
])
def test_only_a_real_policy_decision_authorises(db_session, payment_record, proposal):
    """
    An LLM can emit JSON, and JSON can be shaped like anything. What it cannot
    be is an instance of the policy engine's own dataclass.
    """
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed")
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(db_session, record, proposal,
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.NOT_A_POLICY_DECISION


@pytest.mark.parametrize("decision", [
    pytest.param(PolicyDecision(should_act=False, reason_code=ReasonCode.PROCEED,
                                reason="r", channel="whatsapp_link", cost_paise=50),
                 id="should_act-false"),
    pytest.param(PolicyDecision(should_act=True, reason_code=ReasonCode.HARD_DECLINE,
                                reason="r", channel="whatsapp_link", cost_paise=50),
                 id="non-proceed-reason-code"),
])
def test_a_policy_decision_that_does_not_approve_is_refused(
    db_session, payment_record, decision
):
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed")
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(db_session, record, decision,
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.NOT_A_POLICY_DECISION


@pytest.mark.asyncio
async def test_execute_recovery_refuses_a_forged_decision(
    db_session, payment_record, monkeypatch
):
    """
    End to end: a compromised or mistaken policy layer handing the executor a
    plain dict must not produce an action.
    """
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()

    monkeypatch.setattr(
        recovery_actions, "decide_next_action",
        lambda db, rec, **kw: {"should_act": True, "channel": "whatsapp_link",
                               "cost_paise": 50, "reason_code": "PROCEED",
                               "attempt_number": 0},
    )

    with pytest.raises(AttributeError):
        # execute_recovery reads decision.should_act before the guard sees it,
        # so a dict fails earlier still. Either way no action is dispatched.
        await recovery_actions.execute_recovery(db_session, record)

    assert "WHATSAPP_LINK_SENT" not in actions(db_session)


# --- E. The amount is a property of the channel, never of the proposal ------


@pytest.mark.parametrize("cost_paise", [0, 1, 49, 51, 200, 999999, -50])
def test_a_tampered_cost_is_refused(db_session, payment_record, cost_paise):
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(
        db_session, record, proceed(cost_paise=cost_paise), source=SYNTHETIC_SOURCE
    )

    assert verdict.allowed is False
    assert verdict.code == GuardCode.COST_MISMATCH


@pytest.mark.asyncio
async def test_a_tampered_cost_reaches_no_channel(db_session, payment_record, monkeypatch):
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()

    monkeypatch.setattr(recovery_actions, "decide_next_action",
                        lambda db, rec, **kw: proceed(cost_paise=1))

    result = await recovery_actions.execute_recovery(db_session, record)

    assert result["guard_code"] == GuardCode.COST_MISMATCH
    assert result["cost_paise"] == 0
    assert total_cost(db_session) == 0
    assert "WHATSAPP_LINK_SENT" not in actions(db_session)


def test_spend_ceiling_is_reverified_by_the_guard(db_session, payment_record):
    """
    A decision that policy would never produce - the ceiling on a Rs 3.00
    payment is 45p - must still be refused at the authorization point.
    """
    from app.state_machine import log_audit

    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=300,
                            batch_id="batch_guard")
    db_session.add(record)
    db_session.commit()
    log_audit(db_session, record, action="POLICY_NOTE", cost_paise=40)

    verdict = safety_guard.authorize(db_session, record, proceed(),
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.SPEND_LIMIT


# --- H. Channel must fit the diagnosed failure ------------------------------


@pytest.mark.parametrize("failure_class,channel", [
    ("AUTH_FRICTION", "hinglish_voice"),
    ("AUTH_FRICTION", "silent_retry"),
    ("TRANSIENT_TECHNICAL", "whatsapp_link"),
    ("MANDATE_BALANCE", "hinglish_voice"),
    ("HARD_DECLINE", "whatsapp_link"),
    ("HARD_DECLINE", "silent_retry"),
])
def test_a_channel_outside_the_ladder_is_refused(
    db_session, payment_record, failure_class, channel
):
    record = payment_record(failure_class=failure_class, recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=5000000)
    db_session.add(record)
    db_session.commit()

    cost = safety_guard.CHANNEL_ACTION_COST_PAISE[channel]
    verdict = safety_guard.authorize(
        db_session, record, proceed(channel=channel, cost_paise=cost),
        source=SYNTHETIC_SOURCE,
    )

    assert verdict.allowed is False
    assert verdict.code == GuardCode.CLASS_CHANNEL_MISMATCH


@pytest.mark.parametrize("channel", ["sms_blast", "email", "", None])
def test_an_unknown_channel_is_refused(db_session, payment_record, channel):
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed")
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(
        db_session, record, proceed(channel=channel), source=SYNTHETIC_SOURCE
    )

    assert verdict.allowed is False
    assert verdict.code == GuardCode.UNKNOWN_CHANNEL


def test_an_unclassified_record_authorises_nothing(db_session, payment_record):
    record = payment_record(failure_class=None, recovery_state="DIAGNOSED",
                            error_reason="authentication_failed")
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(db_session, record, proceed(),
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.UNCLASSIFIED


# --- F. State ---------------------------------------------------------------


@pytest.mark.parametrize("state", ["RECOVERED", "FAILED_STOPPED"])
def test_no_action_after_a_terminal_state(db_session, payment_record, state):
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state=state,
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(db_session, record, proceed(),
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.TERMINAL_STATE


@pytest.mark.asyncio
async def test_a_recovered_payment_reaches_no_channel(db_session, payment_record, monkeypatch):
    """
    policy.decide_next_action never inspects recovery_state, so a RECOVERED
    record with attempts left would otherwise be approved and messaged. The
    guard is what makes that unreachable rather than merely unusual.
    """
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="RECOVERED",
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()

    dispatched = []
    for channel, fn in list(recovery_actions.CHANNEL_ACTION_MAP.items()):
        async def spy(db, rec, *a, _c=channel, **kw):
            dispatched.append(_c)
            return {}
        monkeypatch.setitem(recovery_actions.CHANNEL_ACTION_MAP, channel, spy)

    result = await recovery_actions.execute_recovery(db_session, record)

    assert dispatched == []
    assert result["action"] == "declined"
    assert result["guard_code"] == GuardCode.TERMINAL_STATE
    assert record.recovery_state == "RECOVERED"
    assert total_cost(db_session) == 0


def test_no_action_before_diagnosis(db_session, payment_record):
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="INGESTED",
                            error_reason="authentication_failed")
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(db_session, record, proceed(),
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.INVALID_STATE


# --- G. Attempts, staleness and duplicate recovery --------------------------


@pytest.mark.asyncio
async def test_a_duplicate_webhook_stays_idempotent_with_the_guard_in_place(
    db_session, offline
):
    payload = failed_payload("authentication_failed")

    first = await ingest(db_session, payload)
    after_first = db_session.query(AuditTrailEntry).count()
    second = await ingest(db_session, payload)

    assert first["status"] == "ingested"
    assert second["status"] == "duplicate"
    assert db_session.query(PaymentFailureRecord).count() == 1
    assert db_session.query(AuditTrailEntry).count() == after_first
    assert actions(db_session).count("WHATSAPP_LINK_SENT") == 1
    assert BLOCKED not in actions(db_session)


def test_a_stale_decision_is_refused(db_session, payment_record):
    """
    A decision computed at attempt 0 must not be executed once an attempt has
    been recorded. This is the idempotency check: it is what stops the same
    approval being spent twice.
    """
    from app.state_machine import log_audit

    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="INTERVENING",
                            error_reason="authentication_failed", amount=5000000,
                            batch_id="batch_guard")
    db_session.add(record)
    db_session.commit()

    decision = proceed(attempt_number=0)
    assert safety_guard.authorize(db_session, record, decision,
                                  source=SYNTHETIC_SOURCE).allowed is True

    log_audit(db_session, record, action="WHATSAPP_LINK_SENT", cost_paise=50)

    verdict = safety_guard.authorize(db_session, record, decision,
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.STALE_DECISION


def test_the_attempt_cap_is_reverified(db_session, payment_record):
    from app.config import MAX_RETRIES
    from app.state_machine import log_audit

    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="INTERVENING",
                            error_reason="authentication_failed", amount=50000000,
                            batch_id="batch_guard")
    db_session.add(record)
    db_session.commit()
    for _ in range(MAX_RETRIES):
        log_audit(db_session, record, action="WHATSAPP_LINK_SENT", cost_paise=50)

    verdict = safety_guard.authorize(
        db_session, record, proceed(attempt_number=MAX_RETRIES),
        source=SYNTHETIC_SOURCE,
    )

    assert verdict.allowed is False
    assert verdict.code == GuardCode.ATTEMPT_LIMIT


# --- Held for review and confidence ----------------------------------------


def test_a_held_record_is_not_available_to_automation(db_session, payment_record):
    from app.state_machine import log_audit

    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()
    log_audit(db_session, record, action=HELD, actor="system", cost_paise=0)

    verdict = safety_guard.authorize(db_session, record, proceed(),
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.HELD_FOR_REVIEW


def test_a_low_confidence_diagnosis_authorises_nothing(db_session, payment_record):
    from app.state_machine import log_audit

    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()
    log_audit(db_session, record, action="FAILURE_DIAGNOSED_LLM", actor="llm_agent",
              details="uncertain", llm_metadata={"confidence": 0.42})

    verdict = safety_guard.authorize(db_session, record, proceed(),
                                     source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.LOW_CONFIDENCE


def test_a_confident_diagnosis_is_authorised(db_session, payment_record):
    from app.state_machine import log_audit

    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()
    log_audit(db_session, record, action="FAILURE_DIAGNOSED_LLM", actor="llm_agent",
              details="confident", llm_metadata={"confidence": 0.93})

    assert safety_guard.authorize(db_session, record, proceed(),
                                  source=SYNTHETIC_SOURCE).allowed is True


def test_a_weak_customer_reply_is_not_treated_as_diagnosis_confidence(
    db_session, payment_record
):
    """
    CUSTOMER_REPLY_PARSED scores how well a model read a message, not how well
    it diagnosed a failure. Conflating them would let an ambiguous WhatsApp
    reply block the next rung of a ladder.
    """
    from app.state_machine import log_audit

    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=450000)
    db_session.add(record)
    db_session.commit()
    log_audit(db_session, record, action="CUSTOMER_REPLY_PARSED", actor="llm_agent",
              details="unclear", llm_metadata={"confidence": 0.10})

    assert safety_guard.authorize(db_session, record, proceed(),
                                  source=SYNTHETIC_SOURCE).allowed is True


# --- I / J. Source ----------------------------------------------------------


@pytest.mark.parametrize("error_reason", [
    "issuer_3ds_timeout", "psp_handle_unreachable", "invoice_under_query",
    "payment_failed", "payment_cancelled",
])
def test_synthetic_records_are_unaffected_by_the_unmapped_reason_rule(
    db_session, payment_record, error_reason
):
    """
    The seeded dataset deliberately carries codes the rule engine does not
    know - they exist to exercise the model's slow path. Holding them would
    change what the simulator measures rather than protect anyone.
    """
    assert error_reason not in RULE_MAP

    record = payment_record(payment_id=f"pay_synth_{error_reason}",
                            failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason=error_reason, amount=450000,
                            source=SYNTHETIC_SOURCE)
    db_session.add(record)
    db_session.commit()

    assert safety_guard.authorize(db_session, record, proceed(),
                                  source=SYNTHETIC_SOURCE).allowed is True


def test_a_caller_may_not_upgrade_a_synthetic_record_to_the_live_path(
    db_session, payment_record
):
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", amount=450000,
                            source=SYNTHETIC_SOURCE)
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(db_session, record, proceed(), source=LIVE_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == GuardCode.SOURCE_NOT_PERMITTED


def test_an_unrecognised_source_authorises_nothing(db_session, payment_record):
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="DIAGNOSED",
                            error_reason="authentication_failed", source="admin_console")
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(db_session, record, proceed(),
                                     source="admin_console")

    assert verdict.allowed is False
    assert verdict.code == GuardCode.SOURCE_NOT_PERMITTED


# --- The refusal itself -----------------------------------------------------


@pytest.mark.asyncio
async def test_a_block_is_ledgered_and_explains_itself(db_session):
    record = live_record(db_session, error_reason="payment_cancelled")

    await recovery_actions.execute_recovery(db_session, record, source=LIVE_SOURCE)

    entry = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == BLOCKED).one()

    assert entry.actor == "safety_guard"
    assert entry.cost_paise == 0
    assert entry.details.startswith("WHY_WE_DIDNT_ACT:")
    assert GuardCode.UNMAPPED_REASON in entry.details
    assert "whatsapp_link" in entry.details
    assert "payment_cancelled" in entry.details
    assert "nothing was" in entry.details


@pytest.mark.asyncio
async def test_the_ledger_stays_valid_across_a_blocked_flow(db_session):
    record = live_record(db_session, error_reason="payment_failed")

    await recovery_actions.execute_recovery(db_session, record, source=LIVE_SOURCE)
    await recovery_actions.execute_recovery(db_session, record, source=LIVE_SOURCE)

    result = ledger.verify_chain(db_session)

    assert result.valid is True
    assert actions(db_session).count(BLOCKED) == 2


def test_authorize_writes_nothing(db_session, payment_record):
    """The reading half must stay pure, or the verdict is not free to consult."""
    record = payment_record(failure_class="AUTH_FRICTION", recovery_state="RECOVERED",
                            error_reason="authentication_failed")
    db_session.add(record)
    db_session.commit()
    before = db_session.query(AuditTrailEntry).count()

    safety_guard.authorize(db_session, record, proceed(), source=SYNTHETIC_SOURCE)

    assert db_session.query(AuditTrailEntry).count() == before


# --- Wiring -----------------------------------------------------------------


def test_the_guard_knows_every_channel_the_executor_can_perform():
    """
    The guard derives its allowlist from policy's ladders and the executor
    derives its dispatch from channel names. A rung added to one without the
    other would either be silently unperformable or silently unguarded.
    """
    assert set(safety_guard.ALLOWED_CHANNELS) == set(recovery_actions.CHANNEL_ACTION_MAP)


def test_every_allowed_channel_has_a_deterministic_cost():
    for channel in safety_guard.ALLOWED_CHANNELS:
        assert channel in safety_guard.CHANNEL_ACTION_COST_PAISE
