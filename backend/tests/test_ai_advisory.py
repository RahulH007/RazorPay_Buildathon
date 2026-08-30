"""
The AI advises. It never acts.

RecoverOS has always run the model on the classifier's slow path, but what the
model concluded lived only inside a prose `details` string that nothing could
read back. So the system could not show its most defensible claim: that a model
materially improves the diagnosis of a failure Razorpay's error vocabulary does
not cover, while holding no authority whatsoever to spend money or contact a
customer.

This file covers both halves of that claim, and the second half harder than the
first.

What the recommendation is
--------------------------
A structured reading of one failure - interpretation, recommended channel,
confidence, rationale, and the evidence the model was actually shown -
persisted as one zero-cost entry on the existing hash chain. No new table, no
new column: the confidence rides in llm_confidence_bp where every other model
confidence already lives, and the structured body rides in `details` behind a
marker.

Why it cannot act
-----------------
Four independent reasons, each tested here:

  1. The model never names a channel. It names a failure class; the channel is
     read out of policy.ATTEMPT_LADDER, a table in code. There is no path by
     which a model's words become a channel name.
  2. app.ai_advisor imports nothing that can act - no recovery_actions, no
     razorpay_client, no voice_pipeline, no settlement. Enforced by reading the
     module's own imports, not by convention.
  3. safety_guard.authorize accepts a PolicyDecision and refuses anything else
     outright, so a Recommendation offered as a decision is rejected by type.
  4. execute_recovery never reads a recommendation. A record whose advisory
     entry recommends an expensive channel still gets the rung the ladder
     dictates - which is the test that would fail first if any of this were
     ever wired the wrong way round.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import ast
import json
from dataclasses import dataclass

import pytest

from app import ai_advisor, classifier, event_adapter, ledger, llm_cache, recovery_actions, safety_guard
from app.config import CONFIDENCE_THRESHOLD
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.policy import ATTEMPT_LADDER, PolicyDecision, ReasonCode
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.schemas import FailureDiagnosis

UNMAPPED = "psp_handle_unreachable"      # genuinely absent from RULE_MAP
MAPPED = "authentication_failed"         # RULE_MAP -> AUTH_FRICTION


# --- Doubles ----------------------------------------------------------------


@dataclass
class FakeResponse:
    """Shaped exactly like llm_cache.LLMResponse. No network, no cache file."""
    text: str
    model: str = "gemini-3.6-flash"
    input_tokens: int = 120
    output_tokens: int = 48
    latency_ms: int = 310
    cached: bool = True


def canned(monkeypatch, payload):
    """
    Pin llm_cache.call to a fixed answer.

    Patched at the cache seam rather than at diagnose_failure, so the real
    prompt assembly, the real JSON coercion and the real confidence handling
    all still run - the only thing replaced is the network.
    """
    text = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(llm_cache, "call", lambda **kwargs: FakeResponse(text=text))


HIGH_CONFIDENCE = {
    "root_cause_class": "AUTH_FRICTION",
    "technical_explanation": "The payer's UPI handle could not be resolved by the PSP "
                             "directory, so the collect request never reached them.",
    "suggested_action": "Re-send a payment link the payer can open directly.",
    "confidence": 0.91,
}

LOW_CONFIDENCE = {
    "root_cause_class": "B2B_RECEIVABLE",
    "technical_explanation": "Possibly an unpaid invoice, but the error text does not "
                             "say so clearly.",
    "suggested_action": "Have a human read the invoice.",
    "confidence": 0.31,
}


@pytest.fixture
def live_unmapped(db_session, payment_record):
    record = payment_record(
        payment_id="pay_live_unmapped",
        error_reason=UNMAPPED,
        error_description="Beneficiary PSP did not respond to the handle lookup.",
        error_source="bank",
        error_step="payment_initiation",
        source=LIVE_SOURCE,
        recovery_state="INGESTED",
    )
    db_session.add(record)
    db_session.commit()
    return record


def actions(db, payment_id=None):
    query = db.query(AuditTrailEntry)
    if payment_id:
        query = query.filter(AuditTrailEntry.payment_id == payment_id)
    return [e.action for e in query.order_by(AuditTrailEntry.sequence_no)]


def advisory_entry(db, payment_id):
    return (
        db.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == payment_id,
                AuditTrailEntry.action == ai_advisor.ADVISORY_ACTION)
        .order_by(AuditTrailEntry.sequence_no.desc())
        .first()
    )


# =============================================================================
# THE CRITICAL SAFETY TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_a_recommendation_alone_cannot_trigger_a_recovery_action(
        db_session, live_unmapped, monkeypatch):
    """
    THE test this step exists for.

    A live payment, an error code nobody has approved for automation, and a
    confident model saying "send them a payment link". The recommendation is on
    the chain and readable. Nothing was sent, nothing was spent, and no state
    moved - because a recommendation is not an authorisation, and there is no
    code path on which it becomes one.
    """
    canned(monkeypatch, HIGH_CONFIDENCE)
    await classifier.classify(db_session, live_unmapped)

    recommendation = ai_advisor.latest_for(db_session, live_unmapped.payment_id)
    assert recommendation["recommended_channel"] == "whatsapp_link"
    assert recommendation["confidence"] >= CONFIDENCE_THRESHOLD

    before = live_unmapped.recovery_state
    result = await recovery_actions.execute_recovery(
        db_session, live_unmapped, source=LIVE_SOURCE)

    assert result["action"] == "declined"
    assert "WHATSAPP_LINK_SENT" not in actions(db_session, live_unmapped.payment_id)
    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert sum(e.cost_paise or 0 for e in db_session.query(AuditTrailEntry)) == 0
    assert live_unmapped.recovery_state == before


@pytest.mark.asyncio
async def test_the_recommended_channel_has_no_influence_on_what_is_executed(
        db_session, payment_record, monkeypatch):
    """
    The recommendation names the most expensive rung in the system. The record
    is AUTH_FRICTION, whose ladder starts at whatsapp_link. What executes is
    whatsapp_link.

    If the model's channel were ever read by the executor, this is the test
    that would fail, and it would fail loudly rather than by silently costing
    ₹2.00 a call.
    """
    record = payment_record(
        payment_id="pay_ignores_advice", failure_class="AUTH_FRICTION",
        error_reason=MAPPED, recovery_state="DIAGNOSED", source=SYNTHETIC_SOURCE)
    db_session.add(record)
    db_session.commit()

    ai_advisor.record_recommendation(
        db_session, record,
        ai_advisor.Recommendation(
            payment_id=record.payment_id,
            failure_class="B2B_RECEIVABLE",
            interpretation="This is an unpaid invoice.",
            recommended_channel="hinglish_voice",
            model_suggested_action="Call the accounts payable team.",
            confidence=0.99,
            rationale="The description mentions an invoice.",
            evidence={"error_reason": MAPPED},
            review_required=False,
        ))

    monkeypatch.setattr(recovery_actions, "generate_whatsapp_message",
                        _template_message)

    result = await recovery_actions.execute_recovery(
        db_session, record, source=SYNTHETIC_SOURCE)

    assert result["action"] == "whatsapp_link"
    assert result["decision"]["channel"] == "whatsapp_link"
    assert "VOICE_CALL_INITIATED" not in actions(db_session, record.payment_id)
    # The record's class is the deterministic one, untouched by the advice.
    assert record.failure_class == "AUTH_FRICTION"


async def _template_message(record, link_url):
    return f"template for {record.customer_name}", {}, None


def test_the_safety_guard_refuses_a_recommendation_offered_as_a_decision(
        db_session, payment_record):
    """
    Guard check one, exercised with the exact object this step introduces. The
    guard takes a PolicyDecision; a Recommendation is refused by type before a
    single field of it is read.
    """
    record = payment_record(failure_class="AUTH_FRICTION",
                            recovery_state="DIAGNOSED", error_reason=MAPPED)
    db_session.add(record)
    db_session.commit()

    recommendation = ai_advisor.Recommendation(
        payment_id=record.payment_id, failure_class="AUTH_FRICTION",
        interpretation="x", recommended_channel="whatsapp_link",
        model_suggested_action="send a link", confidence=1.0, rationale="y",
        evidence={}, review_required=False)

    verdict = safety_guard.authorize(
        db_session, record, recommendation, source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == safety_guard.GuardCode.NOT_A_POLICY_DECISION
    assert "Recommendation" in verdict.reason


def test_a_recommendation_dict_is_refused_just_as_firmly(db_session, payment_record):
    """The obvious bypass: hand the guard the model's JSON directly."""
    record = payment_record(failure_class="AUTH_FRICTION",
                            recovery_state="DIAGNOSED", error_reason=MAPPED)
    db_session.add(record)
    db_session.commit()

    verdict = safety_guard.authorize(
        db_session, record,
        {"should_act": True, "reason_code": "PROCEED", "channel": "hinglish_voice",
         "cost_paise": 0, "attempt_number": 0},
        source=SYNTHETIC_SOURCE)

    assert verdict.allowed is False
    assert verdict.code == safety_guard.GuardCode.NOT_A_POLICY_DECISION


def test_the_advisor_imports_nothing_that_can_act():
    """
    Structural, not behavioural. A module that cannot import an executor cannot
    call one, however it is later edited - and that is a stronger guarantee
    than any assertion about today's call graph.
    """
    import app.ai_advisor as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported.update(f"{node.module}.{a.name}" for a in node.names)

    forbidden = {
        "app.recovery_actions", "app.razorpay_client", "app.voice_pipeline",
        "app.settlement", "app.inbound", "app.recovery_tick", "razorpay",
        "httpx", "requests",
    }
    assert not (imported & forbidden), f"advisor reaches an executor: {imported & forbidden}"


def test_the_advisor_names_no_channel_the_ladder_does_not_already_contain():
    """
    The model chooses a failure class. The channel is looked up, not generated,
    so the set of things it can ever recommend is bounded by policy.py.
    """
    rungs = {c for steps in ATTEMPT_LADDER.values() for c in steps}

    for channel in ai_advisor.RECOMMENDED_CHANNEL_BY_CLASS.values():
        assert channel is None or channel in rungs


@pytest.mark.asyncio
async def test_recording_a_recommendation_moves_no_state_and_spends_nothing(
        db_session, live_unmapped, monkeypatch):
    canned(monkeypatch, HIGH_CONFIDENCE)

    entry = ai_advisor.record_recommendation(
        db_session, live_unmapped,
        ai_advisor.build(live_unmapped, FailureDiagnosis(**{
            "root_cause_class": "AUTH_FRICTION",
            "technical_explanation": "t", "suggested_action": "s",
            "confidence": 0.9})))

    assert entry.cost_paise == 0
    assert entry.actor == ai_advisor.ADVISORY_ACTOR
    assert live_unmapped.recovery_state == "INGESTED"
    assert ledger.verify_chain(db_session).valid is True


# =============================================================================
# The recommendation itself
# =============================================================================


@pytest.mark.asyncio
async def test_a_high_confidence_diagnosis_produces_a_complete_recommendation(
        db_session, live_unmapped, monkeypatch):
    canned(monkeypatch, HIGH_CONFIDENCE)

    await classifier.classify(db_session, live_unmapped)
    rec = ai_advisor.latest_for(db_session, live_unmapped.payment_id)

    assert rec["failure_class"] == "AUTH_FRICTION"
    assert rec["interpretation"] == HIGH_CONFIDENCE["technical_explanation"]
    assert rec["recommended_channel"] == "whatsapp_link"
    assert rec["model_suggested_action"] == HIGH_CONFIDENCE["suggested_action"]
    assert rec["confidence"] == 0.91
    assert rec["rationale"]
    assert rec["review_required"] is False
    assert rec["advisory"] is True


@pytest.mark.asyncio
async def test_the_evidence_is_what_the_model_was_shown_not_what_it_wrote(
        db_session, live_unmapped, monkeypatch):
    """
    Evidence has to be checkable. These five fields come off the record, so a
    reviewer can compare them against the webhook Razorpay sent rather than
    taking the model's word for what it was looking at.
    """
    canned(monkeypatch, HIGH_CONFIDENCE)
    await classifier.classify(db_session, live_unmapped)

    evidence = ai_advisor.latest_for(db_session, live_unmapped.payment_id)["evidence"]

    assert evidence["error_reason"] == UNMAPPED
    assert evidence["error_description"] == live_unmapped.error_description
    assert evidence["error_source"] == "bank"
    assert evidence["error_step"] == "payment_initiation"
    assert evidence["method"] == live_unmapped.method


@pytest.mark.asyncio
async def test_a_low_confidence_recommendation_is_flagged_for_review(
        db_session, live_unmapped, monkeypatch):
    """
    The reading is still recorded - a weak signal is evidence too - but it is
    marked, and the existing escalation still fires and still refuses to let a
    31%-confident guess set the failure class.
    """
    canned(monkeypatch, LOW_CONFIDENCE)

    await classifier.classify(db_session, live_unmapped)
    rec = ai_advisor.latest_for(db_session, live_unmapped.payment_id)
    trail = actions(db_session, live_unmapped.payment_id)

    assert rec["confidence"] == 0.31
    assert rec["review_required"] is True
    # What the model thought is preserved verbatim...
    assert rec["failure_class"] == "B2B_RECEIVABLE"
    # ...and was not accepted.
    assert live_unmapped.failure_class == "HARD_DECLINE"
    assert "ESCALATED_TO_HUMAN" in trail
    assert "FAILURE_DIAGNOSED_LLM" not in trail


@pytest.mark.asyncio
async def test_malformed_model_output_becomes_a_reviewable_recommendation(
        db_session, live_unmapped, monkeypatch):
    """
    Unparseable output is a weak signal, not a crash. It is recorded at zero
    confidence, flagged for review, and recommends no channel at all - because
    the class it degrades to is HARD_DECLINE, whose ladder is empty.
    """
    canned(monkeypatch, "not json at all <<<>>>")

    await classifier.classify(db_session, live_unmapped)
    rec = ai_advisor.latest_for(db_session, live_unmapped.payment_id)

    assert rec["confidence"] == 0.0
    assert rec["review_required"] is True
    assert rec["recommended_channel"] is None
    assert "unparseable" in rec["interpretation"].lower()


@pytest.mark.asyncio
async def test_a_model_inventing_a_sixth_failure_class_recommends_nothing(
        db_session, live_unmapped, monkeypatch):
    canned(monkeypatch, {"root_cause_class": "COSMIC_RAY",
                         "technical_explanation": "A bit flipped.",
                         "suggested_action": "Pray.", "confidence": 0.99})

    await classifier.classify(db_session, live_unmapped)
    rec = ai_advisor.latest_for(db_session, live_unmapped.payment_id)

    assert rec["recommended_channel"] is None
    assert rec["review_required"] is True
    assert rec["confidence"] == 0.0


@pytest.mark.asyncio
async def test_a_diagnosis_that_raises_records_no_recommendation(
        db_session, live_unmapped, monkeypatch):
    """
    No answer is not a weak answer. Nothing is invented to fill the gap, and
    the existing escalation is what a reviewer sees.
    """
    def explode(**kwargs):
        raise llm_cache.CacheMiss("no recorded response")

    monkeypatch.setattr(llm_cache, "call", explode)

    await classifier.classify(db_session, live_unmapped)

    assert ai_advisor.latest_for(db_session, live_unmapped.payment_id) is None
    assert "ESCALATED_TO_HUMAN" in actions(db_session, live_unmapped.payment_id)


# =============================================================================
# The deterministic path is untouched
# =============================================================================


@pytest.mark.asyncio
async def test_a_rule_map_reason_produces_no_recommendation_at_all(
        db_session, payment_record, monkeypatch):
    """
    The fast path never asks the model, so there is nothing to advise about.
    An advisory entry appearing here would mean the model had been consulted on
    a decision a lookup table already answers.
    """
    def forbidden(**kwargs):
        raise AssertionError("the rule engine must not call the model")

    monkeypatch.setattr(llm_cache, "call", forbidden)

    record = payment_record(payment_id="pay_mapped", error_reason=MAPPED,
                            source=LIVE_SOURCE)
    db_session.add(record)
    db_session.commit()

    failure_class = await classifier.classify(db_session, record)
    trail = actions(db_session, "pay_mapped")

    assert failure_class.value == "AUTH_FRICTION"
    assert ai_advisor.ADVISORY_ACTION not in trail
    assert ai_advisor.latest_for(db_session, "pay_mapped") is None
    classified = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "CLASSIFIED_AUTH_FRICTION").one()
    assert classified.actor == "rule_engine"


@pytest.mark.asyncio
async def test_every_rule_map_reason_still_classifies_exactly_as_before(
        db_session, payment_record, monkeypatch):
    """The whole table, not a sample. This is the regression that matters."""
    def forbidden(**kwargs):
        raise AssertionError("the rule engine must not call the model")

    monkeypatch.setattr(llm_cache, "call", forbidden)

    for index, (reason, expected) in enumerate(classifier.RULE_MAP.items()):
        record = payment_record(payment_id=f"pay_rule_{index}", error_reason=reason)
        db_session.add(record)
        db_session.commit()

        result = await classifier.classify(db_session, record)

        assert result == expected
        assert record.failure_class == expected.value
        assert ai_advisor.latest_for(db_session, record.payment_id) is None


@pytest.mark.asyncio
async def test_the_advisory_entry_costs_nothing_and_is_not_a_recovery_attempt(
        db_session, live_unmapped, monkeypatch):
    """
    Guards the batch's numbers. The new action must not count as an attempt
    against the retry cap, must not appear in the intervention economics, and
    must not add a paisa to spend.
    """
    from app.guardrails import ATTEMPT_ACTIONS, count_attempts, spend_paise
    from app.intervention_economics import INTERVENTION_BY_ACTION

    canned(monkeypatch, HIGH_CONFIDENCE)
    await classifier.classify(db_session, live_unmapped)

    assert ai_advisor.ADVISORY_ACTION not in ATTEMPT_ACTIONS
    assert ai_advisor.ADVISORY_ACTION not in INTERVENTION_BY_ACTION
    assert count_attempts(db_session, live_unmapped) == 0
    assert spend_paise(db_session, live_unmapped) == 0


@pytest.mark.asyncio
async def test_the_advisory_entry_does_not_become_diagnosis_confidence_for_the_guard(
        db_session, live_unmapped, monkeypatch):
    """
    safety_guard reads confidence from FAILURE_DIAGNOSED_LLM only. If the
    advisory entry were folded into that set, a low-confidence advisory could
    start blocking rungs the guard had already cleared - a behaviour change
    smuggled in by a reporting feature.
    """
    assert ai_advisor.ADVISORY_ACTION not in safety_guard.DIAGNOSIS_CONFIDENCE_ACTIONS


# =============================================================================
# Persistence and read-back
# =============================================================================


@pytest.mark.asyncio
async def test_the_recommendation_survives_a_round_trip_through_the_ledger(
        db_session, live_unmapped, monkeypatch):
    canned(monkeypatch, HIGH_CONFIDENCE)
    await classifier.classify(db_session, live_unmapped)

    entry = advisory_entry(db_session, live_unmapped.payment_id)
    parsed = ai_advisor.parse(entry.details)

    assert parsed == ai_advisor.latest_for(db_session, live_unmapped.payment_id)
    assert entry.llm_confidence_bp == 9100        # 0.91 as basis points
    assert entry.llm_model == "gemini-3.6-flash"


@pytest.mark.asyncio
async def test_the_entry_stays_readable_to_a_human_and_carries_the_banner(
        db_session, live_unmapped, monkeypatch):
    """
    The ledger is read by people as well as by code. The structured body sits
    behind a marker so the line above it is still a sentence, and every entry
    states what it is not: an authorisation.
    """
    canned(monkeypatch, HIGH_CONFIDENCE)
    await classifier.classify(db_session, live_unmapped)

    details = advisory_entry(db_session, live_unmapped.payment_id).details
    headline = details.split(ai_advisor.ADVISORY_MARKER)[0]

    assert ai_advisor.ADVISORY_BANNER in headline
    assert "whatsapp_link" in headline
    assert ai_advisor.ADVISORY_MARKER in details


def test_details_without_a_recommendation_parse_to_nothing():
    assert ai_advisor.parse("Just an ordinary ledger line.") is None
    assert ai_advisor.parse(None) is None
    assert ai_advisor.parse(f"prose {ai_advisor.ADVISORY_MARKER}{{broken json") is None


def test_a_record_with_no_recommendation_reads_back_as_none(db_session, payment_record):
    record = payment_record(payment_id="pay_silent")
    db_session.add(record)
    db_session.commit()

    assert ai_advisor.latest_for(db_session, "pay_silent") is None
    assert ai_advisor.latest_for(db_session, "pay_does_not_exist") is None


@pytest.mark.asyncio
async def test_the_most_recent_reading_wins(db_session, live_unmapped, monkeypatch):
    """
    The ledger is append-only, so a re-diagnosis adds rather than replaces. The
    record's current AI reading is the latest one on the chain.
    """
    canned(monkeypatch, LOW_CONFIDENCE)
    await classifier.classify(db_session, live_unmapped)
    assert ai_advisor.latest_for(db_session, live_unmapped.payment_id)["confidence"] == 0.31

    canned(monkeypatch, HIGH_CONFIDENCE)
    ai_advisor.record_recommendation(
        db_session, live_unmapped,
        ai_advisor.build(live_unmapped, FailureDiagnosis(
            root_cause_class="AUTH_FRICTION", technical_explanation="Second look.",
            suggested_action="Send a link.", confidence=0.88)))

    assert ai_advisor.latest_for(db_session, live_unmapped.payment_id)["confidence"] == 0.88


@pytest.mark.asyncio
async def test_many_records_are_read_back_in_one_pass(
        db_session, payment_record, monkeypatch):
    canned(monkeypatch, HIGH_CONFIDENCE)

    for i in range(3):
        record = payment_record(payment_id=f"pay_bulk_{i}", error_reason=UNMAPPED,
                                source=LIVE_SOURCE)
        db_session.add(record)
        db_session.commit()
        await classifier.classify(db_session, record)

    quiet = payment_record(payment_id="pay_bulk_quiet", error_reason=MAPPED)
    db_session.add(quiet)
    db_session.commit()

    found = ai_advisor.latest_for_many(
        db_session, [f"pay_bulk_{i}" for i in range(3)] + ["pay_bulk_quiet"])

    assert set(found) == {"pay_bulk_0", "pay_bulk_1", "pay_bulk_2"}
    assert all(r["recommended_channel"] == "whatsapp_link" for r in found.values())


# =============================================================================
# Through the live webhook path and the APIs
# =============================================================================


@pytest.mark.asyncio
async def test_an_unmapped_razorpay_reason_is_held_and_still_advised(
        db_session, monkeypatch):
    """
    The whole point of the feature, end to end. A live failure Razorpay's
    vocabulary does not map is held for human review - and the reviewer is
    handed the model's reading of it instead of a bare error code.
    """
    canned(monkeypatch, HIGH_CONFIDENCE)

    normalized = event_adapter.normalize_razorpay_payment_failed({
        "account_id": "acc_test",
        "payload": {"payment": {"entity": {
            "id": "pay_webhook_unmapped", "amount": 45000, "currency": "INR",
            "method": "upi", "contact": "+919999999999",
            "error_reason": UNMAPPED,
            "error_description": "Beneficiary PSP did not respond.",
            "error_source": "bank", "error_step": "payment_initiation",
        }}},
    })
    result = await event_adapter.ingest_and_process(db_session, normalized)
    trail = actions(db_session, "pay_webhook_unmapped")

    assert result["status"] == "held_for_review"
    assert ai_advisor.ADVISORY_ACTION in trail
    assert "UNMAPPED_REASON_HELD_FOR_REVIEW" in trail
    assert "WHATSAPP_LINK_SENT" not in trail

    rec = ai_advisor.latest_for(db_session, "pay_webhook_unmapped")
    assert rec["recommended_channel"] == "whatsapp_link"
    assert rec["advisory"] is True


@pytest.mark.asyncio
async def test_the_recovery_api_serves_the_recommendation(
        db_session, live_unmapped, monkeypatch):
    from app.routes import recovery as recovery_routes

    canned(monkeypatch, HIGH_CONFIDENCE)
    await classifier.classify(db_session, live_unmapped)

    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(recovery_routes, "SessionLocal", lambda: db_session)

    payload = await recovery_routes.get_recovery_record(live_unmapped.payment_id)

    assert payload["ai_recommendation"]["recommended_channel"] == "whatsapp_link"
    assert payload["ai_recommendation"]["advisory"] is True


@pytest.mark.asyncio
async def test_the_audit_api_serves_the_recommendation(
        db_session, live_unmapped, monkeypatch):
    from app.routes import audit as audit_routes

    canned(monkeypatch, HIGH_CONFIDENCE)
    await classifier.classify(db_session, live_unmapped)

    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(audit_routes, "SessionLocal", lambda: db_session)

    payload = await audit_routes.get_audit_trail(live_unmapped.payment_id)

    assert payload["ai_recommendation"]["confidence"] == 0.91


@pytest.mark.asyncio
async def test_the_dashboard_reports_the_cohorts_recommendations(
        db_session, payment_record, monkeypatch):
    from app.routes import metrics as metrics_route

    canned(monkeypatch, HIGH_CONFIDENCE)
    for i in range(2):
        record = payment_record(payment_id=f"pay_dash_{i}", error_reason=UNMAPPED,
                                source=LIVE_SOURCE)
        db_session.add(record)
        db_session.commit()
        await classifier.classify(db_session, record)

    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: db_session)

    insight = (await metrics_route.get_dashboard_metrics(scope="live"))["ai_insight"]

    assert insight["advisory_only"] is True
    assert insight["notice"] == ai_advisor.ADVISORY_BANNER
    assert insight["count"] == 2
    assert insight["review_required"] == 0
    assert len(insight["recommendations"]) == 2
    assert insight["recommendations"][0]["payment_id"].startswith("pay_dash_")


@pytest.mark.asyncio
async def test_the_dashboard_insight_respects_the_cohort(
        db_session, payment_record, monkeypatch):
    """
    Scoped like every other figure on the endpoint. A live record's AI reading
    must not appear under a batch it does not belong to.
    """
    from app.routes import metrics as metrics_route

    canned(monkeypatch, HIGH_CONFIDENCE)
    live = payment_record(payment_id="pay_scope_live", error_reason=UNMAPPED,
                          source=LIVE_SOURCE)
    db_session.add(live)
    db_session.commit()
    await classifier.classify(db_session, live)

    batched = payment_record(payment_id="pay_scope_batch", error_reason=MAPPED,
                             batch_id="batch_scope_test")
    db_session.add(batched)
    db_session.commit()

    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: db_session)

    batch = await metrics_route.get_dashboard_metrics(scope="batch",
                                                      batch_id="batch_scope_test")
    every = await metrics_route.get_dashboard_metrics(scope="all")

    assert batch["ai_insight"]["count"] == 0
    assert batch["ai_insight"]["recommendations"] == []
    assert every["ai_insight"]["count"] == 1


@pytest.mark.asyncio
async def test_an_empty_database_reports_an_empty_insight(db_session, monkeypatch):
    from app.routes import metrics as metrics_route

    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(metrics_route, "SessionLocal", lambda: db_session)

    insight = (await metrics_route.get_dashboard_metrics())["ai_insight"]

    assert insight["count"] == 0
    assert insight["recommendations"] == []
    assert insight["advisory_only"] is True


# =============================================================================
# No network
# =============================================================================


@pytest.mark.asyncio
async def test_nothing_in_this_path_reaches_an_external_api(
        db_session, live_unmapped, monkeypatch):
    """
    The conftest fixture blocks the seams; this asserts the advisory path never
    even reaches for one. Every call above ran against a pinned llm_cache, and
    the transport, the SDKs and the live-path flags are all still shut.
    """
    from app import voice_pipeline

    canned(monkeypatch, HIGH_CONFIDENCE)
    await classifier.classify(db_session, live_unmapped)

    assert llm_cache.DEMO_MODE is True
    assert "XXXX" in llm_cache.GEMINI_API_KEY
    assert voice_pipeline.DEMO_MODE is True
    assert db_session.query(RazorpayPaymentLink).count() == 0


@pytest.mark.asyncio
async def test_the_advisory_entry_changes_no_dashboard_metric(
        db_session, payment_record, monkeypatch):
    """
    The batch's numbers, computed twice over identical data - once with the
    advisory entry written, once with it suppressed. Everything a merchant or a
    judge reads is byte-identical.

    Only the ledger height differs, and it must: the chain gained an entry, and
    a chain that claimed otherwise would be the one thing in this system worth
    distrusting.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.database import Base
    from app.routes import metrics as metrics_route

    canned(monkeypatch, HIGH_CONFIDENCE)

    async def seed(session):
        for i in range(4):
            record = PaymentFailureRecord(
                payment_id=f"pay_inv_{i}", amount=100_000, currency="INR",
                method="upi", merchant_id="m", customer_name="C",
                customer_phone="+919999999999", error_reason=UNMAPPED,
                error_description="Beneficiary PSP did not respond.",
                error_source="bank", error_step="payment_initiation",
                recovery_state="INGESTED", batch_id="batch_invariance",
                source=SYNTHETIC_SOURCE, arm="treated")
            session.add(record)
            session.commit()
            await classifier.classify(session, record)

    async def read(session):
        monkeypatch.setattr(session, "close", lambda: None)
        monkeypatch.setattr(metrics_route, "SessionLocal", lambda: session)
        return await metrics_route.get_dashboard_metrics(
            scope="batch", batch_id="batch_invariance")

    await seed(db_session)
    with_advisory = await read(db_session)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    without = sessionmaker(bind=engine)()
    monkeypatch.setattr(ai_advisor, "record_recommendation",
                        lambda *a, **k: None)
    await seed(without)
    without_advisory = await read(without)

    ignored = {"ledger", "ai_insight"}
    assert {k: v for k, v in with_advisory.items() if k not in ignored} ==         {k: v for k, v in without_advisory.items() if k not in ignored}
    assert with_advisory["ledger"]["entries"] ==         without_advisory["ledger"]["entries"] + 4
    assert with_advisory["ai_insight"]["count"] == 4
    assert without_advisory["ai_insight"]["count"] == 0
