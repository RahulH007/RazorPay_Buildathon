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
