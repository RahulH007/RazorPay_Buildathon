"""
Step 1: live payment.failed ingestion, gated Razorpay access, Payment Link
correlation.

TEST ISOLATION
--------------
Nothing here may reach the network. The suite must stay safe even if someone
sets DEMO_MODE=false and drops real Test Mode credentials into .env, so these
tests never rely on DEMO_MODE alone: the `no_network` fixture below replaces
razorpay_client.get_client with something that fails loudly, and it is
autouse, so a test that forgets to mock still cannot make an API call.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import time

import pytest

from app import event_adapter, razorpay_client, recovery_actions
from app.models import AuditTrailEntry, PaymentFailureRecord, RazorpayPaymentLink
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE

REAL_KEY = "rzp_test_1234567890abcd"
REAL_SECRET = "abcdefghijklmnopqrstuv"


class NetworkTouched(AssertionError):
    """Raised if any test tries to build a real Razorpay client."""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """
    Hard stop on real API access, regardless of DEMO_MODE or .env contents.

    This is deliberately at the get_client seam rather than at create_payment_link,
    so a future action that calls the API a different way is caught too.
    """
    def explode(source):
        raise NetworkTouched(
            f"A test attempted a real Razorpay client (source={source!r}). "
            f"Mock razorpay_client.create_payment_link instead."
        )

    monkeypatch.setattr(razorpay_client, "get_client", explode)


@pytest.fixture
def live_credentials(monkeypatch):
    """DEMO_MODE=false with credentials that look real. Still no network."""
    monkeypatch.setattr(razorpay_client, "DEMO_MODE", False)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", REAL_KEY)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", REAL_SECRET)
    # Live creation refuses a loopback callback and config defaults to one, so
    # pin a public value rather than inherit the developer's PUBLIC_BASE_URL.
    monkeypatch.setattr(recovery_actions, "PAYMENT_LINK_CALLBACK_URL", "https://tests.recoveros.example/api/webhooks/razorpay")


def payment_failed_payload(**overrides):
    """A realistic Razorpay payment.failed body."""
    entity = {
        "id": "pay_LiveTest000001",
        "amount": 450000,
        "currency": "INR",
        "method": "card",
        "email": "asha@example.com",
        "contact": "+919876500999",
        "error_source": "bank",
        "error_step": "payment_authorization",
        "error_reason": "authentication_failed",
        "error_description": "Your payment didn't go through as the OTP was not entered.",
        "notes": {"customer_name": "Asha Rao"},
    }
    entity.update(overrides.pop("entity", {}))
    payload = {
        "event": "payment.failed",
        "account_id": "acc_LiveMerchant01",
        "payload": {"payment": {"entity": entity}},
    }
    payload.update(overrides)
    return payload


# --- A. Normalization -------------------------------------------------------


def test_normalizer_maps_the_razorpay_entity():
    n = event_adapter.normalize_razorpay_payment_failed(payment_failed_payload())

    assert n["payment_id"] == "pay_LiveTest000001"
    assert n["amount"] == 450000
    assert n["currency"] == "INR"
    assert n["method"] == "card"
    assert n["customer_phone"] == "+919876500999"
    assert n["customer_email"] == "asha@example.com"
    assert n["customer_name"] == "Asha Rao"
    assert n["merchant_id"] == "acc_LiveMerchant01"
    assert n["error_reason"] == "authentication_failed"
    assert n["source"] == LIVE_SOURCE
    assert n["recovery_state"] == "INGESTED"


def test_normalizer_uses_an_honest_placeholder_for_a_missing_name():
    payload = payment_failed_payload(entity={"notes": {}})
    n = event_adapter.normalize_razorpay_payment_failed(payload)
    assert n["customer_name"] == "Razorpay Customer"


@pytest.mark.parametrize("payload", [
    {},
    {"payload": {}},
    {"payload": {"payment": {"entity": {}}}},
    # No payment id.
    {"account_id": "acc_1", "payload": {"payment": {"entity": {"amount": 100}}}},
    # No amount.
    {"account_id": "acc_1", "payload": {"payment": {"entity": {"id": "pay_x"}}}},
    # No merchant identity.
    {"payload": {"payment": {"entity": {"id": "pay_x", "amount": 100}}}},
    "not a dict",
])
def test_malformed_payloads_are_rejected(payload):
    assert event_adapter.normalize_razorpay_payment_failed(payload) is None


# --- B. Ingestion -----------------------------------------------------------


@pytest.mark.asyncio
async def test_live_ingestion_creates_one_record_and_classifies_it(db_session, monkeypatch):
    monkeypatch.setattr(
        recovery_actions.razorpay_client, "is_configured", lambda source: False)

    n = event_adapter.normalize_razorpay_payment_failed(payment_failed_payload())
    result = await event_adapter.ingest_and_process(db_session, n)

    assert result["status"] == "ingested"
    records = db_session.query(PaymentFailureRecord).all()
    assert len(records) == 1
    assert records[0].source == LIVE_SOURCE
    assert records[0].failure_class == "AUTH_FRICTION"

    actions = [e.action for e in db_session.query(AuditTrailEntry).all()]
    assert actions.count("RECORD_INGESTED") == 1
    assert "CLASSIFIED_AUTH_FRICTION" in actions


@pytest.mark.asyncio
async def test_duplicate_webhook_is_a_true_no_op(db_session, monkeypatch):
    """Razorpay retries delivery; a retry must not re-run the pipeline."""
    monkeypatch.setattr(
        recovery_actions.razorpay_client, "is_configured", lambda source: False)

    n = event_adapter.normalize_razorpay_payment_failed(payment_failed_payload())
    await event_adapter.ingest_and_process(db_session, n)

    before_state = db_session.query(PaymentFailureRecord).one().recovery_state
    before_entries = db_session.query(AuditTrailEntry).count()

    second = await event_adapter.ingest_and_process(db_session, n)

    assert second["status"] == "duplicate"
    assert db_session.query(PaymentFailureRecord).count() == 1
    assert db_session.query(AuditTrailEntry).count() == before_entries
    assert db_session.query(PaymentFailureRecord).one().recovery_state == before_state

    actions = [e.action for e in db_session.query(AuditTrailEntry).all()]
    assert actions.count("RECORD_INGESTED") == 1


# --- C. Recovery and correlation -------------------------------------------


@pytest.mark.asyncio
async def test_live_recovery_creates_payment_link_and_correlation_row(
    db_session, live_credentials, monkeypatch,
):
    created = {}

    def fake_create(source, payload):
        created["source"] = source
        created["payload"] = payload
        return {"id": "plink_TestLink0001", "short_url": "https://rzp.io/i/live01"}

    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", fake_create)

    n = event_adapter.normalize_razorpay_payment_failed(payment_failed_payload())
    await event_adapter.ingest_and_process(db_session, n)

    record = db_session.query(PaymentFailureRecord).one()
    assert record.recovery_state == "INTERVENING"

    sent = db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "WHATSAPP_LINK_SENT"
    ).one()

    link = db_session.query(RazorpayPaymentLink).one()
    assert link.payment_id == "pay_LiveTest000001"
    assert link.amount == 450000
    assert link.currency == "INR"
    assert link.razorpay_payment_link_id == "plink_TestLink0001"
    assert link.razorpay_payment_id is None
    assert link.status == "created"
    # The correlation points at the exact ledger entry recording the action.
    assert link.recovery_action_id == sent.entry_hash

    assert created["source"] == LIVE_SOURCE
    assert created["payload"]["notes"] == {"recoveros_payment_id": "pay_LiveTest000001"}


@pytest.mark.asyncio
async def test_failed_api_creation_leaves_no_correlation_row(
    db_session, live_credentials, monkeypatch, payment_record,
):
    """A row here asserts a real link exists. A failed call must not write one."""
    def boom(source, payload):
        raise RuntimeError("Razorpay said no")

    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", boom)

    record = payment_record(
        payment_id="pay_fail_link", failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING", source=LIVE_SOURCE,
    )
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(db_session, record, source=LIVE_SOURCE)

    assert result["payment_link_created"] is False
    assert "Razorpay said no" in result["error"]
    assert db_session.query(RazorpayPaymentLink).count() == 0
    # The action is still ledgered - the attempt happened.
    assert db_session.query(AuditTrailEntry).filter(
        AuditTrailEntry.action == "WHATSAPP_LINK_SENT").count() == 1


# --- D. Demo and synthetic safety ------------------------------------------


def test_gate_is_closed_in_demo_mode(monkeypatch):
    monkeypatch.setattr(razorpay_client, "DEMO_MODE", True)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", REAL_KEY)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", REAL_SECRET)
    assert razorpay_client.is_configured(LIVE_SOURCE) is False


def test_gate_is_closed_for_synthetic_even_with_live_credentials(live_credentials):
    """The whole point of source: demo data cannot reach the network."""
    assert razorpay_client.is_configured(SYNTHETIC_SOURCE) is False
    assert razorpay_client.is_configured(LIVE_SOURCE) is True


def test_gate_is_closed_when_credentials_are_placeholders(monkeypatch):
    monkeypatch.setattr(razorpay_client, "DEMO_MODE", False)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", "rzp_test_XXXXXXXXXXXXXX")
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", REAL_SECRET)
    assert razorpay_client.is_configured(LIVE_SOURCE) is False


def test_get_client_refuses_rather_than_returning_none(monkeypatch, external_locks):
    # Deliberately lift the autouse isolation to exercise the real refusal
    # path. Safe because DEMO_MODE is forced on first, so get_client refuses
    # before it can build a client - which is the behaviour under test.
    external_locks.restore()
    monkeypatch.setattr(razorpay_client, "DEMO_MODE", True)
    with pytest.raises(razorpay_client.RazorpayNotConfigured):
        razorpay_client.get_client(LIVE_SOURCE)


@pytest.mark.asyncio
async def test_synthetic_recovery_writes_no_correlation_row(db_session, payment_record):
    record = payment_record(
        payment_id="pay_synth_1", failure_class="AUTH_FRICTION",
        recovery_state="INTERVENING",
    )
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(db_session, record)

    assert result["link_url"].startswith("https://rzp.io/i/demo_")
    assert db_session.query(RazorpayPaymentLink).count() == 0


# --- E. Expiry --------------------------------------------------------------


def test_payment_link_expiry_is_about_thirty_minutes_ahead():
    """
    Razorpay requires at least 15 minutes. The old value was exactly 15, so
    request latency could push it under the limit.
    """
    ahead = recovery_actions.payment_link_expiry_epoch() - int(time.time())
    assert 29 * 60 <= ahead <= 31 * 60
    assert recovery_actions.PAYMENT_LINK_EXPIRY_MINUTES == 30


@pytest.mark.asyncio
async def test_reported_expiry_matches_the_timestamp(db_session, payment_record):
    record = payment_record(payment_id="pay_exp_1", failure_class="AUTH_FRICTION")
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(db_session, record)

    assert result["expiry_minutes"] == recovery_actions.PAYMENT_LINK_EXPIRY_MINUTES


@pytest.mark.asyncio
async def test_silent_retry_cannot_reach_razorpay_from_synthetic(db_session, live_credentials, payment_record):
    """
    silent_retry used to build a client on `if not DEMO_MODE` alone, so a
    synthetic record would call the downtime API the moment demo mode was
    turned off. The autouse guard makes any such attempt raise.
    """
    record = payment_record(
        payment_id="pay_silent_1", failure_class="TRANSIENT_TECHNICAL",
        recovery_state="INTERVENING",
    )
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.silent_retry(db_session, record)

    assert "downtimes" not in result
    assert "downtime_check_error" not in result


# --- Callback URL configuration --------------------------------------------


def test_callback_url_is_derived_from_configuration_not_hardcoded():
    """
    It was hardcoded to localhost, which resolves to the payer's own device
    rather than to this service, so a real customer paying on a phone landed
    nowhere.
    """
    from app import config

    assert config.PAYMENT_LINK_CALLBACK_URL == (
        config.PUBLIC_BASE_URL + "/api/webhooks/razorpay")
    assert recovery_actions.PAYMENT_LINK_CALLBACK_URL == config.PAYMENT_LINK_CALLBACK_URL


def test_public_base_url_reads_the_environment(monkeypatch):
    import importlib

    from app import config

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.ngrok-free.dev/")
    reloaded = importlib.reload(config)
    try:
        # Trailing slash trimmed so the joined path never doubles up.
        assert reloaded.PUBLIC_BASE_URL == "https://example.ngrok-free.dev"
        assert reloaded.PAYMENT_LINK_CALLBACK_URL == (
            "https://example.ngrok-free.dev/api/webhooks/razorpay")
    finally:
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
        importlib.reload(config)


@pytest.mark.asyncio
async def test_generated_payload_carries_the_configured_callback_url(
    db_session, live_credentials, monkeypatch, payment_record,
):
    """The value must reach Razorpay's payload, not just live in config."""
    captured = {}

    def fake_create(source, payload):
        captured.update(payload)
        return {"id": "plink_CallbackTest", "short_url": "https://rzp.io/i/cb01"}

    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", fake_create)
    monkeypatch.setattr(recovery_actions, "PAYMENT_LINK_CALLBACK_URL",
                        "https://public.example.dev/api/webhooks/razorpay")

    record = payment_record(payment_id="pay_cb_1", amount=45000,
                            failure_class="AUTH_FRICTION", source=LIVE_SOURCE)
    db_session.add(record)
    db_session.commit()

    await recovery_actions.send_whatsapp_link(db_session, record, source=LIVE_SOURCE)

    assert captured["callback_url"] == "https://public.example.dev/api/webhooks/razorpay"
    assert "localhost" not in captured["callback_url"]


@pytest.mark.asyncio
async def test_synthetic_flow_builds_no_payload_and_calls_nothing(
    db_session, live_credentials, monkeypatch, payment_record,
):
    """
    Even with live credentials and a public callback configured, a synthetic
    record must not reach the API. The source gate, not DEMO_MODE, is what
    guarantees this.
    """
    calls = []

    def spy_create(source, payload):
        calls.append(source)
        return {"id": "plink_SHOULD_NOT_HAPPEN", "short_url": "https://rzp.io/i/nope"}

    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link", spy_create)

    record = payment_record(payment_id="pay_synth_cb", amount=45000,
                            failure_class="AUTH_FRICTION", source=SYNTHETIC_SOURCE)
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(db_session, record)

    assert calls == []
    assert result["link_url"].startswith("https://rzp.io/i/demo_")
    assert db_session.query(RazorpayPaymentLink).count() == 0
