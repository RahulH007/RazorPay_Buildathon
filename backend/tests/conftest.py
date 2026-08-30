"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import PaymentFailureRecord

# Imported once here rather than inside the fixture: `from google import genai`
# is slow enough that paying it per test is noticeable, and both are optional
# at the SDK level even though this project depends on them.
try:  # pragma: no cover - import guard
    import razorpay as razorpay_sdk
except Exception:  # pragma: no cover
    razorpay_sdk = None

try:  # pragma: no cover - import guard
    from google import genai as google_genai
except Exception:  # pragma: no cover
    google_genai = None


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def payment_record():
    def build(**overrides):
        values = {
            "payment_id": "pay_test_001",
            "amount": 100000,
            "currency": "INR",
            "method": "upi",
            "merchant_id": "merchant_test",
            "customer_name": "Test Customer",
            "customer_email": "test@example.com",
            "customer_phone": "+919999999999",
            "error_reason": "bank_technical_error",
            "error_description": "Temporary bank error",
            "recovery_state": "INGESTED",
        }
        values.update(overrides)
        return PaymentFailureRecord(**values)

    return build


# --- External API isolation -------------------------------------------------
#
# The suite must be safe even if someone sets DEMO_MODE=false and puts real
# credentials in .env. Without this, running pytest in that configuration makes
# real Gemini calls (observed: 429 RESOURCE_EXHAUSTED against the live quota),
# would create real Razorpay Payment Links, and would post real text to Sarvam
# for synthesis.
#
# Blocked here rather than in individual test files, because the guarantee has
# to hold for tests nobody remembered to guard.
#
# Every integration gets more than one lock, and they are independent on
# purpose. A flag-based guard alone is only as good as the flag: a test that
# legitimately sets DEMO_MODE=false to exercise a live-path branch would
# silently dissolve it. So each integration is stopped once at the decision
# that selects the live path, once at the function that performs it, and once
# at the SDK or transport underneath. A leak has to defeat all three.
#
# Note where the Razorpay lock deliberately is NOT: create_payment_link stays
# real, because it refuses a loopback callback before it builds a client and
# tests/test_payment_link_callback_is_public.py exercises that refusal. The
# seam is get_client, one layer down.

# Applied with plain setattr and reverted in this fixture's own teardown,
# deliberately NOT through the `monkeypatch` fixture.
#
# `monkeypatch` is a single function-scoped instance shared by a test and every
# fixture that requested it, so a test calling monkeypatch.undo() - reasonably
# believing it undoes its own patch - silently disarms all of these for the
# rest of that test. That happened: tests/test_concurrency_idempotency.py did
# it, and with DEMO_MODE=false and real Test Mode credentials in .env the suite
# opened one connection to Razorpay per run until a socket sentinel caught it.
#
# A guarantee this important must not depend on every future test author
# knowing what monkeypatch.undo() reaches.
class _Locks:
    """Saves what it replaces, and puts it back."""

    def __init__(self):
        self._saved = []

    def setattr(self, target, name, value):  # noqa: A003 - mirrors monkeypatch
        self._saved.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def restore(self):
        for target, name, original in reversed(self._saved):
            setattr(target, name, original)
        self._saved.clear()


@pytest.fixture
def external_locks():
    """
    The lifted-latch handle, for the rare test that must exercise a real
    refusal path.

    Requesting this fixture and calling `.restore()` says "I am deliberately
    lifting the isolation" in a way a reviewer can grep for. That is the whole
    point of it existing: the previous way of expressing the same intent was
    monkeypatch.undo(), which is what a test also writes when it means to undo
    only its own patch - and the two are indistinguishable until something
    reaches the network.
    """
    locks = _Locks()
    try:
        yield locks
    finally:
        locks.restore()


@pytest.fixture(autouse=True)
def _no_external_apis(external_locks):
    from app import llm_cache, razorpay_client, voice_pipeline

    locks = external_locks

    # --- Razorpay ---
    def refuse_client(source):
        raise AssertionError(
            f"pytest attempted a real Razorpay client (source={source!r}). "
            f"Mock razorpay_client.create_payment_link in the test."
        )

    locks.setattr(razorpay_client, "get_client", refuse_client)

    if razorpay_sdk is not None:
        def refuse_sdk(*args, **kwargs):
            raise AssertionError(
                "pytest attempted to construct razorpay.Client directly. "
                "Every live call must go through app.razorpay_client."
            )

        locks.setattr(razorpay_sdk, "Client", refuse_sdk)

    # --- Gemini ---
    # Forces llm_cache onto the replay path, where a missing recording raises
    # CacheMiss instead of calling Gemini. Individual tests may still set this
    # themselves; they set the same value.
    locks.setattr(llm_cache, "DEMO_MODE", True)

    # Second lock, independent of the flag: llm_cache refuses to go live
    # against a placeholder key, so even a test that sets DEMO_MODE=false
    # raises CacheMiss rather than reaching the API.
    locks.setattr(llm_cache, "GEMINI_API_KEY", "XXXXXXXXXXXXXXXXXXXXXX")

    if google_genai is not None:
        def refuse_genai(*args, **kwargs):
            raise AssertionError(
                "pytest attempted to construct a Gemini client. Record "
                "responses with `make refresh-llm-cache` instead."
            )

        locks.setattr(google_genai, "Client", refuse_genai)

    # --- Sarvam TTS ---
    # voice_pipeline.generate_voice_audio posts to api.sarvam.ai whenever
    # DEMO_MODE is false and the key is real. Nothing blocked this before, so
    # a developer holding a Sarvam key was synthesising real audio, and paying
    # for it, on every run of the voice tests.
    locks.setattr(voice_pipeline, "DEMO_MODE", True)
    locks.setattr(voice_pipeline, "SARVAM_API_KEY", "XXXXXXXXXXXXXXXXXXXXXX")

    async def refuse_tts(*args, **kwargs):
        raise AssertionError(
            "pytest attempted a real Sarvam TTS call. Use voice_pipeline."
            "mock_tts, or patch sarvam_tts in the test."
        )

    locks.setattr(voice_pipeline, "sarvam_tts", refuse_tts)

    # --- Transport backstop ---
    # The last net, under anything added later that reaches out over async
    # HTTP. Only AsyncClient is blocked: starlette's TestClient is a subclass
    # of the *synchronous* httpx.Client, so route tests are unaffected.
    async def refuse_async_post(*args, **kwargs):
        raise AssertionError(
            "pytest attempted an outbound httpx.AsyncClient POST. No test may "
            "reach the network."
        )

    locks.setattr(httpx.AsyncClient, "post", refuse_async_post)
