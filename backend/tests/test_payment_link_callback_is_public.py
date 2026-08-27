"""
Priority 5: the callback URL a live Payment Link actually carries.

This exists because of a real artefact, not a hypothetical. Fetching
`plink_TUP5uZtv5eko8x` from Razorpay Test Mode - a link this system genuinely
created on 2026-08-26 at 12:48 - returns:

    "callback_url": "http://localhost:8000/api/webhooks/razorpay"

`localhost` resolves to the *payer's* device, so that link returned a real
customer to nothing. The link created at 13:54 the same day, after
PUBLIC_BASE_URL was set, carries the public host correctly.

tests/test_razorpay_integration.py already proves the plumbing: the callback is
derived from config rather than hardcoded, config reads the environment, and the
value reaches Razorpay's payload. All three pass whatever PUBLIC_BASE_URL holds -
including its default, which is `http://localhost:8000`. That is the hole the
broken link fell through: nothing checks that the value in force is reachable
from outside this machine.

So this file asserts the one thing those do not - that *this deployment* would
not repeat it.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import importlib
import os
from urllib.parse import urlparse

import pytest

from app import config

# Hosts that resolve to the machine running the code rather than to a public
# address. A Payment Link carrying any of these strands the payer.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}

CONFIGURED = os.getenv("PUBLIC_BASE_URL")


def test_the_default_callback_is_loopback_which_is_why_this_check_exists(monkeypatch):
    """
    Characterises the hazard rather than guarding it.

    With PUBLIC_BASE_URL unset, config falls back to localhost and every other
    callback test still passes. A reader who wonders why the check below is
    worth having can see the failure mode here.
    """
    import dotenv

    # config calls load_dotenv() at import, so clearing the variable is not
    # enough on a machine that has it in .env - the reload would put it back.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)

    reloaded = importlib.reload(config)
    try:
        assert urlparse(reloaded.PAYMENT_LINK_CALLBACK_URL).hostname in LOOPBACK_HOSTS
    finally:
        monkeypatch.undo()
        importlib.reload(config)


@pytest.mark.skipif(
    not CONFIGURED,
    reason="PUBLIC_BASE_URL is unset, so there is no deployment value to check.",
)
def test_this_deployment_would_not_ship_a_loopback_callback():
    """
    The check that would have caught the 12:48 link before a payer saw it.

    Skipped rather than failed where PUBLIC_BASE_URL is unset - a checkout with
    no environment configured is not a misconfigured deployment, and turning
    that into a red suite would train people to ignore it.
    """
    parsed = urlparse(config.PAYMENT_LINK_CALLBACK_URL)

    assert parsed.scheme in ("http", "https"), config.PAYMENT_LINK_CALLBACK_URL
    assert parsed.hostname not in LOOPBACK_HOSTS, (
        f"PAYMENT_LINK_CALLBACK_URL is {config.PAYMENT_LINK_CALLBACK_URL!r}. "
        f"A payer redirected there lands on their own device. Set "
        f"PUBLIC_BASE_URL to the tunnel or deployment host."
    )
    assert parsed.path == "/api/webhooks/razorpay"


@pytest.mark.skipif(
    not CONFIGURED,
    reason="PUBLIC_BASE_URL is unset, so there is no deployment value to check.",
)
def test_the_live_gate_and_the_callback_agree():
    """
    The two settings that must be true together.

    A live Payment Link is only created when the gate is open; the callback is
    only useful when it is public. Either alone is harmless - the combination of
    an open gate and a loopback callback is what produced a real broken link.
    """
    from app import razorpay_client
    from app.razorpay_client import LIVE_SOURCE

    if not razorpay_client.is_configured(LIVE_SOURCE):
        pytest.skip("The live gate is closed here, so no link can be created.")

    assert urlparse(config.PAYMENT_LINK_CALLBACK_URL).hostname not in LOOPBACK_HOSTS


# --- The guard itself -------------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://localhost:8000/api/webhooks/razorpay",
    "https://localhost/api/webhooks/razorpay",
    "http://127.0.0.1:8000/api/webhooks/razorpay",
    "http://0.0.0.0:8000/api/webhooks/razorpay",
    "http://[::1]:8000/api/webhooks/razorpay",
    "http://LOCALHOST:8000/api/webhooks/razorpay",
])
def test_loopback_callbacks_are_recognised(url):
    from app import razorpay_client

    assert razorpay_client.callback_is_loopback(url) is True


@pytest.mark.parametrize("url", [
    "https://buffer-voicing-font.ngrok-free.dev/api/webhooks/razorpay",
    "https://recoveros.example.com/api/webhooks/razorpay",
    "http://203.0.113.10:8000/api/webhooks/razorpay",
    None,
    "",
])
def test_public_and_absent_callbacks_are_allowed(url):
    """
    An absent callback is not a trap: Razorpay shows its own confirmation page,
    which is a real destination. Only a loopback host looks configured and is not.
    """
    from app import razorpay_client

    assert razorpay_client.callback_is_loopback(url) is False


def test_create_payment_link_refuses_before_it_builds_a_client(monkeypatch):
    """
    The backstop at the single seam. The refusal must come before get_client, so
    no credential is used and no socket is opened for a call that cannot work.
    """
    from app import razorpay_client

    def boom(source):
        raise AssertionError("a client was built for a loopback callback")

    monkeypatch.setattr(razorpay_client, "get_client", boom)

    with pytest.raises(razorpay_client.LoopbackCallbackRefused) as excinfo:
        razorpay_client.create_payment_link(
            razorpay_client.LIVE_SOURCE,
            {"amount": 45000, "callback_url": "http://localhost:8000/api/webhooks/razorpay"},
        )

    assert "PUBLIC_BASE_URL" in str(excinfo.value)
    # It is a configuration refusal, not a transport error to be retried.
    assert isinstance(excinfo.value, razorpay_client.RazorpayNotConfigured)


@pytest.mark.asyncio
async def test_a_live_link_with_a_loopback_callback_is_blocked_and_ledgered(
        db_session, payment_record, monkeypatch):
    """
    The whole point: nothing is created, nothing is sent, and the ledger says
    why rather than leaving a reviewer to guess at a silence.
    """
    from app import recovery_actions
    from app.models import AuditTrailEntry, RazorpayPaymentLink
    from app.razorpay_client import LIVE_SOURCE

    def boom_create(source, payload):
        raise AssertionError("the API was called with a loopback callback")

    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: source == LIVE_SOURCE)
    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link",
                        boom_create)
    monkeypatch.setattr(recovery_actions, "PAYMENT_LINK_CALLBACK_URL",
                        "http://localhost:8000/api/webhooks/razorpay")

    record = payment_record(payment_id="pay_loopback_1", amount=45000,
                            failure_class="AUTH_FRICTION",
                            recovery_state="INTERVENING", source=LIVE_SOURCE)
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(
        db_session, record, source=LIVE_SOURCE)

    assert result["action"] == "blocked"
    assert result["reason"] == "loopback_callback_url"
    assert result["payment_link_created"] is False
    assert result["customer_contacted"] is False

    recorded = [e.action for e in db_session.query(AuditTrailEntry).all()]
    assert recorded == ["LIVE_LINK_BLOCKED_LOOPBACK_CALLBACK"]

    entry = db_session.query(AuditTrailEntry).one()
    assert entry.actor == "system"
    assert entry.cost_paise == 0
    assert "WHY_WE_DIDNT_ACT" in entry.details
    assert "PUBLIC_BASE_URL" in entry.details

    # No link, no message, no spend - and no demo URL handed to a live customer
    # as though it were genuine.
    assert db_session.query(RazorpayPaymentLink).count() == 0
    assert "WHATSAPP_LINK_SENT" not in recorded
    assert "link_url" not in result


@pytest.mark.asyncio
async def test_the_same_record_proceeds_with_a_public_callback(
        db_session, payment_record, monkeypatch):
    """The control: the callback is what blocked it, not the rest of the rig."""
    from app import recovery_actions
    from app.models import AuditTrailEntry, RazorpayPaymentLink
    from app.razorpay_client import LIVE_SOURCE

    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: source == LIVE_SOURCE)
    monkeypatch.setattr(recovery_actions.razorpay_client, "create_payment_link",
                        lambda source, payload: {"id": "plink_PublicCb01",
                                                 "short_url": "https://rzp.io/i/pub01"})
    monkeypatch.setattr(recovery_actions, "PAYMENT_LINK_CALLBACK_URL",
                        "https://public.example.dev/api/webhooks/razorpay")

    record = payment_record(payment_id="pay_loopback_2", amount=45000,
                            failure_class="AUTH_FRICTION",
                            recovery_state="INTERVENING", source=LIVE_SOURCE)
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(
        db_session, record, source=LIVE_SOURCE)

    recorded = [e.action for e in db_session.query(AuditTrailEntry).all()]
    assert result["action"] == "whatsapp_link"
    assert "LIVE_LINK_BLOCKED_LOOPBACK_CALLBACK" not in recorded
    assert "WHATSAPP_LINK_SENT" in recorded
    assert db_session.query(RazorpayPaymentLink).count() == 1


@pytest.mark.asyncio
async def test_the_synthetic_path_still_works_with_a_loopback_callback(
        db_session, payment_record, monkeypatch):
    """
    Demo mode must keep running on localhost. The guard is about links Razorpay
    creates for real payers; a demo placeholder redirects nobody.
    """
    from app import recovery_actions
    from app.models import AuditTrailEntry
    from app.razorpay_client import SYNTHETIC_SOURCE

    monkeypatch.setattr(recovery_actions, "PAYMENT_LINK_CALLBACK_URL",
                        "http://localhost:8000/api/webhooks/razorpay")

    record = payment_record(payment_id="pay_loopback_3", amount=45000,
                            failure_class="AUTH_FRICTION",
                            recovery_state="INTERVENING", source=SYNTHETIC_SOURCE)
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(db_session, record)

    recorded = [e.action for e in db_session.query(AuditTrailEntry).all()]
    assert result["action"] == "whatsapp_link"
    assert result["link_url"].startswith("https://rzp.io/i/demo_")
    assert "LIVE_LINK_BLOCKED_LOOPBACK_CALLBACK" not in recorded
    assert "WHATSAPP_LINK_SENT" in recorded
