"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import PaymentFailureRecord


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
# real Gemini calls (observed: 429 RESOURCE_EXHAUSTED against the live quota)
# and would create real Razorpay Payment Links.
#
# Both seams are blocked here rather than in individual test files, because the
# guarantee has to hold for tests nobody remembered to guard.

@pytest.fixture(autouse=True)
def _no_external_apis(monkeypatch):
    from app import llm_cache, razorpay_client

    def refuse_client(source):
        raise AssertionError(
            f"pytest attempted a real Razorpay client (source={source!r}). "
            f"Mock razorpay_client.create_payment_link in the test."
        )

    monkeypatch.setattr(razorpay_client, "get_client", refuse_client)

    # Forces llm_cache onto the replay path, where a missing recording raises
    # CacheMiss instead of calling Gemini. Individual tests may still set this
    # themselves; they set the same value.
    monkeypatch.setattr(llm_cache, "DEMO_MODE", True)
