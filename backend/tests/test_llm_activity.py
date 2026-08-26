"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from app import ledger
from app.routes.llm import build_activity


def test_activity_reports_model_work_from_the_ledger(db_session):
    ledger.append_entry(
        db_session, payment_id="pay_a1", action="FAILURE_DIAGNOSED_LLM",
        actor="llm_agent", details="d", llm_model="gemini-3.6-flash",
        llm_input_tokens=180, llm_output_tokens=64, llm_latency_ms=400,
        llm_confidence_bp=8800,
    )
    ledger.append_entry(
        db_session, payment_id="pay_a2", action="CUSTOMER_REPLY_PARSED",
        actor="llm_agent", details="d", llm_model="gemini-3.6-flash",
        llm_input_tokens=90, llm_output_tokens=30, llm_latency_ms=200,
        llm_confidence_bp=9100,
    )
    ledger.append_entry(
        db_session, payment_id="pay_a3", action="CLASSIFIED_AUTH_FRICTION",
        actor="rule_engine", details="d",
    )
    db_session.commit()

    activity = build_activity(db_session)

    assert activity["total_calls"] == 2
    assert activity["by_model"]["gemini-3.6-flash"] == 2
    assert activity["by_action"]["FAILURE_DIAGNOSED_LLM"] == 1
    assert activity["total_input_tokens"] == 270
    assert activity["mean_latency_ms"] == 300
    assert activity["classification_split"] == {"rule_engine": 1, "llm_agent": 0}


def test_activity_counts_rejections(db_session):
    ledger.append_entry(
        db_session, payment_id="pay_b1", action="LLM_OUTPUT_REJECTED",
        actor="policy_engine", details="hallucinated amount",
        llm_model="gemini-3.6-flash", llm_latency_ms=210,
    )
    db_session.commit()

    assert build_activity(db_session)["rejections"] == 1


def test_activity_is_empty_on_a_fresh_ledger(db_session):
    activity = build_activity(db_session)

    assert activity["total_calls"] == 0
    assert activity["mean_latency_ms"] == 0
    assert activity["classification_split"] == {"rule_engine": 0, "llm_agent": 0}


def test_activity_is_scoped_to_the_current_batch(db_session, payment_record):
    """
    The ledger is append-only, so a re-run adds entries rather than replacing
    them. Summing the whole table reported every run ever performed as one
    enormous run - 342 classifications for a 65-record dataset.
    """
    from app.models import PaymentFailureRecord  # noqa: F401

    record = payment_record(payment_id="pay_scope_1", batch_id="batch_now")
    db_session.add(record)
    db_session.commit()

    # A previous run's entries, still in the ledger and correctly so.
    ledger.append_entry(
        db_session, payment_id="pay_old", batch_id="batch_old",
        action="CLASSIFIED_AUTH_FRICTION", actor="rule_engine", details="old",
    )
    ledger.append_entry(
        db_session, payment_id="pay_old", batch_id="batch_old",
        action="FAILURE_DIAGNOSED_LLM", actor="llm_agent", details="old",
        llm_model="gemini-3.6-flash", llm_latency_ms=100, llm_confidence_bp=9000,
    )
    # This run.
    ledger.append_entry(
        db_session, payment_id="pay_scope_1", batch_id="batch_now",
        action="CLASSIFIED_MANDATE_BALANCE", actor="rule_engine", details="new",
    )
    ledger.append_entry(
        db_session, payment_id="pay_scope_1", batch_id="batch_now",
        action="FAILURE_DIAGNOSED_LLM", actor="llm_agent", details="new",
        llm_model="gemini-3.6-flash", llm_latency_ms=200, llm_confidence_bp=8000,
    )
    db_session.commit()

    activity = build_activity(db_session)

    assert activity["batches_counted"] == ["batch_now"]
    assert activity["total_calls"] == 1
    assert activity["mean_latency_ms"] == 200
    assert activity["classification_split"] == {"rule_engine": 1, "llm_agent": 0}


def test_interpretations_expose_what_the_model_returned(db_session, payment_record):
    record = payment_record(payment_id="pay_interp_1", batch_id="batch_now")
    db_session.add(record)
    db_session.commit()

    ledger.append_entry(
        db_session, payment_id="pay_interp_1", batch_id="batch_now",
        action="FAILURE_DIAGNOSED_LLM", actor="llm_agent",
        details="Mandate presented without balance. Suggested action (recorded, not executed): re-present after salary.",
        llm_model="gemini-3.6-flash", llm_latency_ms=412,
        llm_input_tokens=180, llm_output_tokens=64, llm_confidence_bp=8800,
    )
    db_session.commit()

    [entry] = build_activity(db_session)["interpretations"]

    assert entry["action"] == "FAILURE_DIAGNOSED_LLM"
    assert entry["confidence"] == 0.88
    assert entry["latency_ms"] == 412
    assert "re-present after salary" in entry["details"]
    assert entry["entry_hash"]
