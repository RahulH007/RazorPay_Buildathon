"""
Proof that the test suite cannot reach Razorpay, Gemini, or Sarvam.

This is a test about the tests. The suite runs on a machine whose .env carries
DEMO_MODE=false and real credentials, so "we are in demo mode" has never been
the thing keeping pytest off the network - the autouse fixture in conftest is.
That fixture is load-bearing and entirely invisible, which is exactly the kind
of guarantee that rots silently: it was written for Razorpay and Gemini, and a
Sarvam TTS call was added to voice_pipeline afterwards and went unguarded for
as long as it existed.

Each integration is locked three times over, and the locks are independent:

    the flag that selects the live path
    the function that performs the call
    the SDK or transport underneath it

Every layer gets its own test, because a test that only proves the outermost
one would still pass on the day someone legitimately sets DEMO_MODE=false to
exercise a live branch - which is precisely when the guarantee matters.

One deliberate non-lock is asserted too. create_payment_link stays real, since
it refuses a loopback callback before it builds a client and
tests/test_payment_link_callback_is_public.py exercises that refusal. Stubbing
it in conftest would make that whole file vacuous, so a test here pins it.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import httpx
import pytest

from app import llm_cache, razorpay_client, recovery_actions, voice_pipeline
from app.models import RazorpayPaymentLink
from app.razorpay_client import LIVE_SOURCE

REAL_LOOKING_KEY = "rzp_test_1234567890abcd"
REAL_LOOKING_SECRET = "abcdefghijklmnopqrstuv"


# --- Razorpay ---------------------------------------------------------------


def test_the_razorpay_client_cannot_be_built_even_with_live_credentials(monkeypatch):
    """Lock one: the seam every live Razorpay call must pass through."""
    monkeypatch.setattr(razorpay_client, "DEMO_MODE", False)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_ID", REAL_LOOKING_KEY)
    monkeypatch.setattr(razorpay_client, "RAZORPAY_KEY_SECRET", REAL_LOOKING_SECRET)

    assert razorpay_client.is_configured(LIVE_SOURCE) is True

    with pytest.raises(AssertionError) as excinfo:
        razorpay_client.get_client(LIVE_SOURCE)

    assert "real Razorpay client" in str(excinfo.value)


def test_the_razorpay_sdk_cannot_be_constructed_directly():
    """
    Lock two: the SDK itself, for anything that bypasses app.razorpay_client.
    """
    razorpay_sdk = pytest.importorskip("razorpay")

    with pytest.raises(AssertionError) as excinfo:
        razorpay_sdk.Client(auth=(REAL_LOOKING_KEY, REAL_LOOKING_SECRET))

    assert "razorpay.Client" in str(excinfo.value)


def test_create_payment_link_is_deliberately_left_real():
    """
    The one seam conftest must NOT stub.

    create_payment_link refuses a loopback callback before it builds a client,
    and an entire test file rests on that refusal. If conftest ever stubs this
    function, those tests keep passing while proving nothing - so the shape of
    the isolation is pinned here rather than left to memory.
    """
    with pytest.raises(razorpay_client.LoopbackCallbackRefused):
        razorpay_client.create_payment_link(
            LIVE_SOURCE,
            {"callback_url": "http://localhost:8000/api/webhooks/razorpay"},
        )


@pytest.mark.asyncio
async def test_a_live_configured_send_still_creates_no_payment_link(
    db_session, payment_record, monkeypatch
):
    """
    End to end through the application path, with the live gate forced open and
    a publicly routable callback, so nothing but the fixture stands in the way.
    """
    monkeypatch.setattr(recovery_actions.razorpay_client, "is_configured",
                        lambda source: True)
    monkeypatch.setattr(recovery_actions, "PAYMENT_LINK_CALLBACK_URL",
                        "https://tests.recoveros.example/api/webhooks/razorpay")

    record = payment_record(failure_class="AUTH_FRICTION",
                            recovery_state="INTERVENING",
                            error_reason="authentication_failed",
                            source=LIVE_SOURCE)
    db_session.add(record)
    db_session.commit()

    result = await recovery_actions.send_whatsapp_link(
        db_session, record, source=LIVE_SOURCE)

    assert result["payment_link_created"] is False
    assert "AssertionError" in result["error"]
    assert db_session.query(RazorpayPaymentLink).count() == 0


# --- Gemini -----------------------------------------------------------------


def test_an_unrecorded_gemini_call_raises_rather_than_reaching_the_api():
    """Lock one: replay is pinned, so a miss is a CacheMiss, not a request."""
    assert llm_cache.DEMO_MODE is True

    with pytest.raises(llm_cache.CacheMiss):
        llm_cache.call(
            model="gemini-3.6-flash",
            prompt_version=1,
            inputs={"task": "isolation_probe", "nonce": "never-recorded"},
            contents="probe",
        )


def test_gemini_stays_blocked_even_when_a_test_turns_demo_mode_off(monkeypatch):
    """
    Lock two, and the important one: a test that legitimately sets
    DEMO_MODE=false to exercise a live branch must not thereby open the network.
    The placeholder key is what holds when the flag does not.
    """
    monkeypatch.setattr(llm_cache, "DEMO_MODE", False)

    with pytest.raises(llm_cache.CacheMiss) as excinfo:
        llm_cache.call(
            model="gemini-3.6-flash",
            prompt_version=1,
            inputs={"task": "isolation_probe", "nonce": "still-never-recorded"},
            contents="probe",
        )

    assert "placeholder" in str(excinfo.value).lower()


def test_the_gemini_sdk_cannot_be_constructed_directly():
    """Lock three: the SDK underneath llm_cache."""
    genai = pytest.importorskip("google.genai")

    with pytest.raises(AssertionError) as excinfo:
        genai.Client(api_key="AIzaSyRealLookingKeyMaterial")

    assert "Gemini client" in str(excinfo.value)


def test_cache_replay_still_works(monkeypatch):
    """
    The isolation must not have broken the thing it protects. A recorded
    response is still replayed verbatim, which is what makes the demo's head
    hash reproducible.
    """
    inputs = {"task": "isolation_probe", "nonce": "recorded"}
    key = llm_cache.cache_key("gemini-3.6-flash", 1, inputs)
    monkeypatch.setattr(llm_cache, "_STORE", {
        key: {
            "text": "replayed answer",
            "model": "gemini-3.6-flash",
            "input_tokens": 11,
            "output_tokens": 7,
            "latency_ms": 1234,
            "recorded_at": "2026-08-26T00:00:00+00:00",
            "inputs": inputs,
        }
    })

    response = llm_cache.call(
        model="gemini-3.6-flash", prompt_version=1, inputs=inputs,
        contents="probe",
    )

    assert response.text == "replayed answer"
    assert response.cached is True
    assert response.latency_ms == 1234


# --- Sarvam TTS -------------------------------------------------------------


@pytest.mark.asyncio
async def test_sarvam_tts_cannot_be_called():
    """Lock two: the function that performs the synthesis."""
    with pytest.raises(AssertionError) as excinfo:
        await voice_pipeline.sarvam_tts("Namaste")

    assert "Sarvam" in str(excinfo.value)


@pytest.mark.asyncio
async def test_voice_audio_uses_the_mock_even_with_a_real_looking_key(
    db_session, payment_record, monkeypatch
):
    """Lock one: the flag that selects the live synthesis path."""
    monkeypatch.setattr(voice_pipeline, "SARVAM_API_KEY", "sarvam_real_looking_key")

    record = payment_record(failure_class="B2B_RECEIVABLE",
                            recovery_state="INTERVENING",
                            error_reason="invoice_overdue_15d")
    db_session.add(record)
    db_session.commit()

    audio_url = await voice_pipeline.generate_voice_audio(db_session, record)

    assert audio_url.startswith(f"/api/voice/{record.payment_id}")


@pytest.mark.asyncio
async def test_voice_audio_refuses_rather_than_synthesising_when_the_flag_is_off(
    db_session, payment_record, monkeypatch
):
    """
    The flag and the function are independent locks. With DEMO_MODE forced off
    and a real-looking key, the live branch is selected - and still cannot
    reach the network, because the call itself is blocked.
    """
    monkeypatch.setattr(voice_pipeline, "DEMO_MODE", False)
    monkeypatch.setattr(voice_pipeline, "SARVAM_API_KEY", "sarvam_real_looking_key")

    record = payment_record(failure_class="B2B_RECEIVABLE",
                            recovery_state="INTERVENING",
                            error_reason="invoice_overdue_15d")
    db_session.add(record)
    db_session.commit()

    with pytest.raises(AssertionError) as excinfo:
        await voice_pipeline.generate_voice_audio(db_session, record)

    assert "Sarvam" in str(excinfo.value)


# --- Transport --------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbound_async_http_is_blocked():
    """Lock three: the transport under anything added later."""
    async with httpx.AsyncClient() as client:
        with pytest.raises(AssertionError) as excinfo:
            await client.post("https://api.sarvam.ai/text-to-speech", json={})

    assert "reach the network" in str(excinfo.value)


def test_the_synchronous_test_client_still_works(db_session, monkeypatch):
    """
    The transport block must not have caught starlette's TestClient, which is a
    subclass of the *synchronous* httpx.Client. Several route tests depend on
    it, so the boundary is asserted rather than assumed.
    """
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routes import recovery as recovery_routes

    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(recovery_routes, "SessionLocal", lambda: db_session)

    response = TestClient(app).post("/api/recovery/tick")

    assert response.status_code == 200
    assert response.json()["dry_run"] is True


# --- The pins themselves ----------------------------------------------------


def test_a_test_calling_monkeypatch_undo_cannot_disarm_the_isolation(monkeypatch):
    """
    The regression. `monkeypatch` is one function-scoped instance shared by a
    test and every fixture that requested it, so a test that patches something
    of its own and then calls undo() to put it back used to revert *all* of
    these locks for the rest of that test.

    That is not hypothetical. tests/test_concurrency_idempotency.py did exactly
    that, and with DEMO_MODE=false and real Test Mode credentials in .env the
    suite opened one connection to api.razorpay.com on every run until a
    socket-level sentinel caught it. The locks now go on with plain setattr and
    come off in the fixture's own teardown, so undo() cannot reach them.

    A test that genuinely needs the isolation lifted asks for the
    `external_locks` fixture and says so - see
    test_razorpay_integration.test_get_client_refuses_rather_than_returning_none.
    """
    monkeypatch.setattr(razorpay_client, "DEMO_MODE", False)
    monkeypatch.undo()

    assert llm_cache.DEMO_MODE is True
    assert "XXXX" in llm_cache.GEMINI_API_KEY
    assert voice_pipeline.DEMO_MODE is True
    with pytest.raises(AssertionError, match="real Razorpay client"):
        razorpay_client.get_client(LIVE_SOURCE)


def test_every_live_path_flag_is_pinned_shut_during_tests():
    """
    A single place a reviewer can look to see what the suite guarantees,
    independent of whatever .env happens to contain on this machine.
    """
    assert llm_cache.DEMO_MODE is True
    assert "XXXX" in llm_cache.GEMINI_API_KEY
    assert voice_pipeline.DEMO_MODE is True
    assert "XXXX" in voice_pipeline.SARVAM_API_KEY
