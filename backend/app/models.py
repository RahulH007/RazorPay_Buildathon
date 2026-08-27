"""
RecoverOS ORM Models
SQLAlchemy models for PaymentFailureRecord, AuditTrailEntry, and BatchRun.

Money is stored as integer paise throughout, and audit timestamps as integer
microseconds since the Unix epoch. Both choices exist so that ledger hashes are
byte-reproducible across machines and language runtimes — see app/ledger.py.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, String, Integer, Text, DateTime,
    ForeignKey, UniqueConstraint, event, text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class LedgerAppendOnlyError(RuntimeError):
    """Raised when something attempts to mutate or delete a committed entry."""


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

    # "treated" or "control". Persisted rather than recomputed so the arm a
    # record was actually measured in cannot drift if the assignment rule
    # changes later.
    arm = Column(String(10), nullable=True, index=True)

    # A customer-stated intent to pay by a given date. Set from the inbound
    # reply path; read by the policy engine as a deferral, never as a promise
    # we trust - the attempt resumes automatically once the date passes.
    promise_to_pay_at = Column(DateTime, nullable=True)

    # Where this record came from: "synthetic" for the seeded dataset,
    # "razorpay_webhook" for a live signed payment.failed event. Only the
    # latter may reach the real Razorpay API - see razorpay_client.
    source = Column(String(30), nullable=False, default="synthetic", index=True)

    # Timestamps
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    audit_trail = relationship("AuditTrailEntry", back_populates="payment_record",
                               order_by="AuditTrailEntry.sequence_no")


class AuditTrailEntry(Base):
    """
    One immutable link in the ledger hash chain.

    `sequence_no`, `prev_hash`, and `entry_hash` are all UNIQUE. The constraint
    on prev_hash is what makes a chain fork structurally impossible: forking
    would require two rows claiming the same predecessor.
    """
    __tablename__ = "audit_trail_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String(50), ForeignKey("payment_failure_records.payment_id"),
                        nullable=False, index=True)
    # Which run this action belongs to. Hashed, so spend cannot be silently
    # reattributed to a different batch.
    batch_id = Column(String(50), nullable=True, index=True)

    # Chain columns
    sequence_no = Column(Integer, nullable=False, unique=True, index=True)
    prev_hash = Column(String(64), nullable=False, unique=True)
    entry_hash = Column(String(64), nullable=False, unique=True, index=True)

    # Microseconds since the Unix epoch (UTC). Integer so the hash preimage is
    # stable — SQLite renders DateTime as driver-dependent TEXT.
    timestamp_us = Column(Integer, nullable=False)

    action = Column(String(100), nullable=False)
    actor = Column(String(20), nullable=False)  # rule_engine, llm_agent, system, customer
    details = Column(Text, nullable=True)

    # Integer paise. Never a float: float arithmetic is not reproducible and
    # would make the hash disagree between runtimes.
    cost_paise = Column(Integer, nullable=False, default=0)

    # LLM metadata (present only when the action involved an LLM call).
    # Confidence is basis points (0-10000) for the same reason cost is paise.
    llm_model = Column(String(50), nullable=True)
    llm_input_tokens = Column(Integer, nullable=True)
    llm_output_tokens = Column(Integer, nullable=True)
    llm_latency_ms = Column(Integer, nullable=True)
    llm_confidence_bp = Column(Integer, nullable=True)

    # Relationships
    payment_record = relationship("PaymentFailureRecord", back_populates="audit_trail")

    @property
    def cost_inr(self) -> float:
        """Display helper. Never use for arithmetic that feeds a hash."""
        return (self.cost_paise or 0) / 100.0

    @property
    def llm_confidence(self) -> float | None:
        """Display helper: basis points back to a 0.0-1.0 float."""
        if self.llm_confidence_bp is None:
            return None
        return self.llm_confidence_bp / 10000.0


class ConsentRecord(Base):
    """
    Customer-level communication consent.

    Keyed on a hash of the phone number rather than the number itself: the
    registry only ever answers "is this contact suppressed?", so it has no
    reason to hold a raw identifier.

    Consent belongs to the contact, not the payment. That is the entire point
    — a per-payment flag lets the same person be contacted again on their next
    failure, which is the compliance failure this table exists to prevent.
    """
    __tablename__ = "consent_records"
    __table_args__ = (
        UniqueConstraint("contact_hash", "channel", name="uq_consent_contact_channel"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    contact_hash = Column(String(64), nullable=False, index=True)
    channel = Column(String(20), nullable=False, default="all")  # whatsapp, voice, sms, all
    opted_out = Column(Boolean, nullable=False, default=True)

    # Provenance — an auditor asks not just whether consent was withdrawn but
    # how it was captured.
    source = Column(String(30), nullable=False)  # dtmf_9, whatsapp_reply, api, merchant_upload
    payment_id = Column(String(50), nullable=True)
    recorded_at_us = Column(Integer, nullable=False)


class RazorpayPaymentLink(Base):
    """
    A Payment Link this system created at Razorpay, and what became of it.

    This table is the authoritative correlation record. The `notes` field on the
    Razorpay link carries the same payment id, but notes are attacker-supplied
    from our point of view - they arrive back inside a webhook body - so they
    are a hint used to find this row, never the thing trusted to prove which
    RecoverOS record a payment belongs to.

    One RecoverOS payment may be chased more than once, so there is no single
    pending link column on PaymentFailureRecord: each attempt is a row here.
    """
    __tablename__ = "razorpay_payment_links"

    id = Column(Integer, primary_key=True, autoincrement=True)

    payment_id = Column(
        String(50), ForeignKey("payment_failure_records.payment_id"),
        nullable=False, index=True,
    )

    # The entry_hash of the WHATSAPP_LINK_SENT ledger entry that created this
    # link. A hash rather than a row id: it ties the link to the exact,
    # tamper-evident audit entry recording the action, so the correlation is
    # only valid while that entry's content is unaltered.
    recovery_action_id = Column(String(64), nullable=False, index=True)

    razorpay_payment_link_id = Column(String(64), nullable=False, unique=True, index=True)

    # Null until the link is actually paid. Populated at settlement (Step 2).
    razorpay_payment_id = Column(String(64), nullable=True, index=True)

    status = Column(String(20), nullable=False, default="created")  # created, paid
    amount = Column(Integer, nullable=False)  # paise, matching PaymentFailureRecord
    currency = Column(String(10), nullable=False, default="INR")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))


class BatchRun(Base):
    """Tracks a batch simulation run."""
    __tablename__ = "batch_runs"

    batch_id = Column(String(50), primary_key=True, index=True)
    status = Column(String(20), nullable=False, default="PENDING")  # PENDING, RUNNING, COMPLETED
    seed = Column(Integer, nullable=True)
    total_records = Column(Integer, default=0)
    processed_records = Column(Integer, default=0)
    recovered_count = Column(Integer, default=0)
    total_gmv = Column(Integer, default=0)          # paise
    recovered_gmv = Column(Integer, default=0)      # paise
    channel_cost_paise = Column(Integer, default=0)  # paise

    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


# --- Append-only enforcement (ORM layer) ------------------------------------
# SQLite triggers (installed below) cover direct database access. These
# listeners cover the ORM path, so an accidental in-process mutation fails
# loudly instead of silently invalidating the chain.

@event.listens_for(AuditTrailEntry, "before_update")
def _block_audit_update(mapper, connection, target):
    raise LedgerAppendOnlyError(
        f"Audit entries are append-only; attempted UPDATE on sequence "
        f"{target.sequence_no} (payment {target.payment_id})."
    )


@event.listens_for(AuditTrailEntry, "before_delete")
def _block_audit_delete(mapper, connection, target):
    raise LedgerAppendOnlyError(
        f"Audit entries are append-only; attempted DELETE on sequence "
        f"{target.sequence_no} (payment {target.payment_id})."
    )


APPEND_ONLY_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS audit_entries_no_update
    BEFORE UPDATE ON audit_trail_entries
    BEGIN
        SELECT RAISE(ABORT, 'audit_trail_entries is append-only: UPDATE blocked');
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_entries_no_delete
    BEFORE DELETE ON audit_trail_entries
    BEGIN
        SELECT RAISE(ABORT, 'audit_trail_entries is append-only: DELETE blocked');
    END;
    """,
)


def install_append_only_triggers(engine) -> bool:
    """
    Install SQLite triggers that reject UPDATE and DELETE on the ledger table.

    This is what gives the tamper demo its meaning: the guarantee survives
    someone opening the database file directly rather than going through the
    ORM. Returns False on non-SQLite backends, where an equivalent should be
    expressed as a role grant instead.
    """
    if engine.dialect.name != "sqlite":
        return False

    with engine.begin() as connection:
        for statement in APPEND_ONLY_TRIGGERS:
            connection.execute(text(statement))
    return True


def drop_append_only_triggers(engine) -> bool:
    """Remove the append-only triggers. Used only by the tamper demo."""
    if engine.dialect.name != "sqlite":
        return False

    with engine.begin() as connection:
        connection.execute(text("DROP TRIGGER IF EXISTS audit_entries_no_update"))
        connection.execute(text("DROP TRIGGER IF EXISTS audit_entries_no_delete"))
    return True
