"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from app import ledger
from app.routes.llm import build_activity


def test_activity_reports_model_work_from_the_ledger(db_session):
    ledger.append_entry(
        db_session, payment_id="pay_a1", action="FAILURE_DIAGNOSED_LLM",
        actor="llm_agent", details="d", llm_model="gemini-2.0-flash",
        llm_input_tokens=180, llm_output_tokens=64, llm_latency_ms=400,
        llm_confidence_bp=8800,
    )
    ledger.append_entry(
        db_session, payment_id="pay_a2", action="CUSTOMER_REPLY_PARSED",
        actor="llm_agent", details="d", llm_model="gemini-2.0-flash",
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
    assert activity["by_model"]["gemini-2.0-flash"] == 2
    assert activity["by_action"]["FAILURE_DIAGNOSED_LLM"] == 1
    assert activity["total_input_tokens"] == 270
    assert activity["mean_latency_ms"] == 300
    assert activity["classification_split"] == {"rule_engine": 1, "llm_agent": 0}


def test_activity_counts_rejections(db_session):
    ledger.append_entry(
        db_session, payment_id="pay_b1", action="LLM_OUTPUT_REJECTED",
        actor="policy_engine", details="hallucinated amount",
        llm_model="gemini-2.0-flash", llm_latency_ms=210,
    )
    db_session.commit()

    assert build_activity(db_session)["rejections"] == 1


def test_activity_is_empty_on_a_fresh_ledger(db_session):
    activity = build_activity(db_session)

    assert activity["total_calls"] == 0
    assert activity["mean_latency_ms"] == 0
    assert activity["classification_split"] == {"rule_engine": 0, "llm_agent": 0}
