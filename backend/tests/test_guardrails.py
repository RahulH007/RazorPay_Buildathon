from app.config import MAX_RETRIES
from app.guardrails import (
    check_cac_ceiling,
    check_retry_cap,
    check_opt_out,
    run_all_guards,
)
from app.state_machine import log_audit


def test_opt_out_detects_english_and_hinglish_messages():
    assert check_opt_out("STOP sending payment reminders") is True
    assert check_opt_out("Please mat karo") is True
    assert check_opt_out("I will pay tomorrow") is False


def test_retry_cap_halts_after_maximum_retries(db_session, payment_record):
    record = payment_record()
    db_session.add(record)
    db_session.commit()

    for _ in range(MAX_RETRIES):
        log_audit(db_session, record, "RETRY_SILENT_ATTEMPT")

    assert check_retry_cap(db_session, record) is True
    allowed, reason = run_all_guards(db_session, record)
    assert allowed is False
    assert reason.startswith("RETRY_CAP:")


def test_cac_ceiling_halts_when_record_cost_reaches_limit(db_session, payment_record):
    record = payment_record(amount=10000)
    db_session.add(record)
    db_session.commit()

    log_audit(db_session, record, "WHATSAPP_LINK_SENT", cost_paise=1500)

    assert check_cac_ceiling(db_session, record) is True
    allowed, reason = run_all_guards(db_session, record)
    assert allowed is False
    assert reason.startswith("CAC_CEILING:")
