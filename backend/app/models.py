"""
RecoverOS ORM Models
SQLAlchemy models for PaymentFailureRecord, AuditTrailEntry, and BatchRun.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime,
    Enum as SAEnum, ForeignKey, Boolean, JSON,
)
from sqlalchemy.orm import relationship

from app.database import Base


class PaymentFailureRecord(Base):
    """Core record for a failed payment being tracked for recovery."""
    __tablename__ = "payment_failure_records"

    payment_id = Column(String(50), primary_key=True, index=True)
    amount = Column(Integer, nullable=False)  # Amount in paise
    currency = Column(String(10), default="INR")
    method = Column(String(20), nullable=False)  # upi, card, emandate, netbanking, wallet
    subscription_id = Column(String(50), nullable=True)
    invoice_id = Column(String(50), nullable=True)
    merchant_id = Column(String(50), nullable=False)

    # Customer info
    customer_name = Column(String(100), nullable=False)
    customer_email = Column(String(100), nullable=True)
    customer_phone = Column(String(20), nullable=False)

    # Error details
    error_source = Column(String(20), nullable=True)  # bank, gateway, customer, internal
    error_step = Column(String(50), nullable=True)
    error_reason = Column(String(100), nullable=False)
    error_description = Column(Text, nullable=True)

    # Classification & state
    failure_class = Column(String(30), nullable=True)
    recovery_state = Column(String(20), nullable=False, default="INGESTED")
    recovery_channel = Column(String(30), nullable=True)

    # Batch linkage
    batch_id = Column(String(50), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    audit_trail = relationship("AuditTrailEntry", back_populates="payment_record",
                               order_by="AuditTrailEntry.timestamp")


class AuditTrailEntry(Base):
    """Immutable audit log entry for every action taken on a payment record."""
    __tablename__ = "audit_trail_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String(50), ForeignKey("payment_failure_records.payment_id"),
                        nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    action = Column(String(100), nullable=False)
    actor = Column(String(20), nullable=False)  # rule_engine, llm_agent, system, customer
    details = Column(Text, nullable=True)
    cost_incurred_inr = Column(Float, default=0.0)

    # LLM metadata (present only when the action involved an LLM call)
    llm_model = Column(String(50), nullable=True)
    llm_input_tokens = Column(Integer, nullable=True)
    llm_output_tokens = Column(Integer, nullable=True)
    llm_latency_ms = Column(Integer, nullable=True)
    llm_confidence = Column(Float, nullable=True)

    # Relationships
    payment_record = relationship("PaymentFailureRecord", back_populates="audit_trail")


class BatchRun(Base):
    """Tracks a batch simulation run."""
    __tablename__ = "batch_runs"

    batch_id = Column(String(50), primary_key=True, index=True)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, RUNNING, COMPLETED
    total_records = Column(Integer, default=0)
    processed_records = Column(Integer, default=0)
    recovered_count = Column(Integer, default=0)
    total_gmv = Column(Integer, default=0)       # in paise
    recovered_gmv = Column(Integer, default=0)    # in paise
    channel_cost = Column(Float, default=0.0)     # in INR

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
