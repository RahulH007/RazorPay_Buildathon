"""
RecoverOS Ledger
Tamper-evident hash chain over every audit entry.

Design rule: hash only integers and length-prefixed bytes.
Never floats, never formatted datetimes.

Rationale
---------
* **Length prefixes** — plain concatenation is ambiguous. ("ab", "c") and
  ("a", "bc") produce an identical digest, so content could shift between
  adjacent fields without changing the hash. Every field carries a 4-byte
  big-endian length header.
* **Integer money (paise)** — floats introduce non-deterministic arithmetic
  (0.1 + 0.2 != 0.3) and disagree between language runtimes, which would break
  any independent verifier. Money is integer paise everywhere, matching the
  convention already used for `PaymentFailureRecord.amount`.
* **Integer timestamps (microseconds since epoch)** — SQLite stores DateTime as
  TEXT and the exact rendering depends on the driver, so a formatted timestamp
  is not a stable preimage.
* **NFC normalization** — audit details carry Rupee signs and Hinglish text.
  Normalizing guarantees one byte representation per visual string.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditTrailEntry, LedgerAppendOnlyError  # noqa: F401 (re-export)

# The chain root. A sentinel rather than NULL: with a UNIQUE index on
# prev_hash, exactly one row can ever carry it, which makes "there is one
# chain" a schema guarantee. SQLite permits multiple NULLs under a unique
# index, which would silently allow several independently valid-looking chains.
GENESIS_PREV_HASH = "0" * 64

# Bumping this invalidates every previously computed hash. It is recorded in
# the golden fixture test so a change cannot land silently.
PREIMAGE_VERSION = 1

MAX_APPEND_RETRIES = 5


class LedgerConflictError(RuntimeError):
    """Raised when an append could not win its optimistic-concurrency race."""


# --- Primitive encoders -----------------------------------------------------


def _field(raw: bytes) -> bytes:
    """Length-prefix a field so boundaries are unambiguous."""
    return len(raw).to_bytes(4, "big") + raw


def _text(value: Optional[str]) -> bytes:
    """Encode optional text. The leading tag distinguishes None from ''."""
    if value is None:
        return b"\x00"
    normalized = unicodedata.normalize("NFC", str(value))
    return b"\x01" + normalized.encode("utf-8")


def _int(value: int) -> bytes:
    """
    Encode a required integer as fixed-width signed big-endian.

    Floats are rejected rather than coerced. Silently calling int() on a float
    would truncate 24.5 to 24 and put a wrong-but-plausible number into a hash
    that is meant to be evidence.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(
            f"Ledger integers must be int, got {type(value).__name__}: {value!r}. "
            "Money is integer paise and confidence is integer basis points."
        )
    return value.to_bytes(8, "big", signed=True)


def _int_opt(value: Optional[int]) -> bytes:
    """Encode an optional integer. The leading tag distinguishes None from 0."""
    if value is None:
        return b"\x00"
    return b"\x01" + _int(value)


# Clock indirection. Production always uses wall time; the demo receipt swaps
# in a fixed virtual clock so that its ledger head hash is reproducible. A
# real ledger must carry real timestamps, so this hook exists for the
# reproducibility demo only and is never used by the API.
_clock = None


def set_clock(fn) -> None:
    """Install a deterministic clock. Pass None to restore wall time."""
    global _clock
    _clock = fn


def now_us() -> int:
    """Current UTC time as integer microseconds since the Unix epoch."""
    if _clock is not None:
        return _clock()
    return int(datetime.now(timezone.utc).timestamp() * 1_000_000)


def us_to_iso(timestamp_us: Optional[int]) -> Optional[str]:
    """Render integer microseconds as an ISO-8601 string for display only."""
    if timestamp_us is None:
        return None
    return datetime.fromtimestamp(timestamp_us / 1_000_000, tz=timezone.utc).isoformat()


# --- Canonical preimage -----------------------------------------------------


def canonical(
    *,
    prev_hash: str,
    sequence_no: int,
    payment_id: str,
    batch_id: Optional[str] = None,
    timestamp_us: int,
    action: str,
    actor: str,
    details: Optional[str] = None,
    cost_paise: int = 0,
    llm_model: Optional[str] = None,
    llm_input_tokens: Optional[int] = None,
    llm_output_tokens: Optional[int] = None,
    llm_latency_ms: Optional[int] = None,
    llm_confidence_bp: Optional[int] = None,
) -> bytes:
    """
    Build the canonical byte preimage for one ledger entry.

    Field order is part of the format. Changing the order, the set of fields,
    or any encoder is a breaking change: bump PREIMAGE_VERSION and rebuild.

    `batch_id` is hashed rather than kept as loose metadata: which run a spend
    belongs to is exactly the kind of context an auditor needs pinned down.
    """
    return b"".join(
        _field(part)
        for part in (
            _int(PREIMAGE_VERSION),
            _text(prev_hash),
            _int(sequence_no),
            _text(payment_id),
            _text(batch_id),
            _int(timestamp_us),
            _text(action),
            _text(actor),
            _text(details),
            _int(cost_paise),
            _text(llm_model),
            _int_opt(llm_input_tokens),
            _int_opt(llm_output_tokens),
            _int_opt(llm_latency_ms),
            _int_opt(llm_confidence_bp),
        )
    )


def compute_entry_hash(**fields) -> str:
    """SHA-256 of the canonical preimage, as lowercase hex."""
    return hashlib.sha256(canonical(**fields)).hexdigest()


def entry_fields(entry: AuditTrailEntry) -> dict:
    """Extract the hashed fields from a persisted entry."""
    return {
        "prev_hash": entry.prev_hash,
        "sequence_no": entry.sequence_no,
        "payment_id": entry.payment_id,
        "batch_id": entry.batch_id,
        "timestamp_us": entry.timestamp_us,
        "action": entry.action,
        "actor": entry.actor,
        "details": entry.details,
        "cost_paise": entry.cost_paise or 0,
        "llm_model": entry.llm_model,
        "llm_input_tokens": entry.llm_input_tokens,
        "llm_output_tokens": entry.llm_output_tokens,
        "llm_latency_ms": entry.llm_latency_ms,
        "llm_confidence_bp": entry.llm_confidence_bp,
    }


# --- Append -----------------------------------------------------------------


def get_head(db: Session) -> Optional[AuditTrailEntry]:
    """Return the highest-sequence entry, or None for an empty ledger."""
    return (
        db.query(AuditTrailEntry)
        .order_by(AuditTrailEntry.sequence_no.desc())
        .first()
    )


def append_entry(
    db: Session,
    *,
    payment_id: str,
    action: str,
    batch_id: Optional[str] = None,
    actor: str = "system",
    details: Optional[str] = None,
    cost_paise: int = 0,
    timestamp_us: Optional[int] = None,
    llm_model: Optional[str] = None,
    llm_input_tokens: Optional[int] = None,
    llm_output_tokens: Optional[int] = None,
    llm_latency_ms: Optional[int] = None,
    llm_confidence_bp: Optional[int] = None,
) -> AuditTrailEntry:
    """
    Append one entry to the chain.

    Concurrency is handled optimistically rather than with a lock. A fork of
    the chain would require two rows sharing a prev_hash, which the UNIQUE
    index forbids, so a racing writer loses on IntegrityError, re-reads the
    head, and retries. The guarantee is enforced by the schema, not by the
    caller holding a lock correctly — which is what makes it hold across
    threads, event loops, and separate uvicorn worker processes alike.
    """
    last_error: Optional[Exception] = None

    for _ in range(MAX_APPEND_RETRIES):
        head = get_head(db)
        sequence_no = 0 if head is None else head.sequence_no + 1
        prev_hash = GENESIS_PREV_HASH if head is None else head.entry_hash

        fields = {
            "prev_hash": prev_hash,
            "sequence_no": sequence_no,
            "payment_id": payment_id,
            "batch_id": batch_id,
            "timestamp_us": now_us() if timestamp_us is None else timestamp_us,
            "action": action,
            "actor": actor,
            "details": details,
            "cost_paise": cost_paise,
            "llm_model": llm_model,
            "llm_input_tokens": llm_input_tokens,
            "llm_output_tokens": llm_output_tokens,
            "llm_latency_ms": llm_latency_ms,
            "llm_confidence_bp": llm_confidence_bp,
        }

        entry = AuditTrailEntry(entry_hash=compute_entry_hash(**fields), **fields)
        db.add(entry)

        try:
            db.commit()
        except IntegrityError as exc:
            # Another writer claimed this sequence_no / prev_hash first.
            last_error = exc
            db.rollback()
            continue

        db.refresh(entry)
        return entry

    raise LedgerConflictError(
        f"Could not append after {MAX_APPEND_RETRIES} attempts: {last_error}"
    )


# --- Verify -----------------------------------------------------------------


@dataclass
class VerificationResult:
    valid: bool
    entries_checked: int
    head_hash: Optional[str] = None
    first_broken_sequence: Optional[int] = None
    reason: Optional[str] = None
    scope: str = "chain"

    def to_dict(self) -> dict:
        return asdict(self)


def verify_chain(db: Session) -> VerificationResult:
    """
    Walk the whole ledger and check three invariants:

    1. Every entry's stored hash matches a recomputation of its content.
    2. Every entry's prev_hash equals the previous entry's hash (linkage).
    3. Sequence numbers start at 0 and are contiguous (nothing was deleted).
    """
    entries = (
        db.query(AuditTrailEntry).order_by(AuditTrailEntry.sequence_no.asc()).all()
    )

    if not entries:
        return VerificationResult(
            valid=True, entries_checked=0, reason="Ledger is empty"
        )

    expected_prev = GENESIS_PREV_HASH

    for index, entry in enumerate(entries):
        if entry.sequence_no != index:
            return VerificationResult(
                valid=False,
                entries_checked=index,
                first_broken_sequence=entry.sequence_no,
                reason=(
                    f"Sequence gap: expected {index}, found {entry.sequence_no}. "
                    "An entry was deleted or reordered."
                ),
            )

        if entry.prev_hash != expected_prev:
            return VerificationResult(
                valid=False,
                entries_checked=index,
                first_broken_sequence=entry.sequence_no,
                reason=(
                    f"Broken link at sequence {entry.sequence_no}: prev_hash "
                    f"{entry.prev_hash[:16]}... does not match preceding entry "
                    f"hash {expected_prev[:16]}..."
                ),
            )

        recomputed = compute_entry_hash(**entry_fields(entry))
        if recomputed != entry.entry_hash:
            return VerificationResult(
                valid=False,
                entries_checked=index,
                first_broken_sequence=entry.sequence_no,
                reason=(
                    f"Content tampered at sequence {entry.sequence_no} "
                    f"(payment {entry.payment_id}, action {entry.action}): "
                    f"stored hash {entry.entry_hash[:16]}... but content "
                    f"hashes to {recomputed[:16]}..."
                ),
            )

        expected_prev = entry.entry_hash

    return VerificationResult(
        valid=True,
        entries_checked=len(entries),
        head_hash=entries[-1].entry_hash,
        reason="Chain intact",
    )


def verify_payment(db: Session, payment_id: str) -> VerificationResult:
    """
    Verify the content integrity of one payment's entries.

    Linkage and contiguity are global properties, so a per-payment slice can
    only confirm that each of its entries still hashes to its stored value.
    Call verify_chain() for the whole-ledger guarantee.
    """
    entries = (
        db.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == payment_id)
        .order_by(AuditTrailEntry.sequence_no.asc())
        .all()
    )

    for entry in entries:
        recomputed = compute_entry_hash(**entry_fields(entry))
        if recomputed != entry.entry_hash:
            return VerificationResult(
                valid=False,
                entries_checked=len(entries),
                first_broken_sequence=entry.sequence_no,
                reason=(
                    f"Content tampered at sequence {entry.sequence_no} "
                    f"(action {entry.action})"
                ),
                scope="payment",
            )

    return VerificationResult(
        valid=True,
        entries_checked=len(entries),
        head_hash=entries[-1].entry_hash if entries else None,
        reason="All entries for this payment hash correctly",
        scope="payment",
    )
