"""
RecoverOS AI Advisor
What the model concluded, recorded so a person can read it - and nothing more.

The architecture this fits into reads:

    AI diagnoses -> deterministic policy decides -> safety guard authorizes
    -> executor performs

Everything in this module belongs to the first arrow and stops there. The model
has always run on the classifier's slow path, but its reading lived only inside
a prose `details` string that nothing could read back, so the system could not
show its most defensible claim: that a model materially improves the diagnosis
of failures Razorpay's error vocabulary does not cover, while holding no
authority whatsoever to spend money or contact a customer.

Four independent reasons a recommendation cannot become an action
-----------------------------------------------------------------
1. The model never names a channel. It names one of five failure classes, and
   the channel is read out of policy.ATTEMPT_LADDER - a table in code, written
   by a person. There is no path by which the model's words become a channel
   name, because the recommendation's `recommended_channel` field is filled by
   a dictionary lookup this module performs, not by anything the model wrote.

2. This module imports nothing that can act. No recovery_actions, no
   razorpay_client, no voice_pipeline, no settlement, no HTTP client. A module
   that cannot import an executor cannot call one, however it is later edited,
   and tests/test_ai_advisory.py enforces that by reading these imports.

3. safety_guard.authorize accepts a PolicyDecision and refuses anything else
   outright, by type, before reading a single field. A Recommendation offered
   as a decision is rejected the same way a dict of the model's raw JSON is.

4. execute_recovery never reads a recommendation. It calls
   policy.decide_next_action, which reads the record's failure_class and the
   ladder, and nothing else. An advisory entry recommending an expensive rung
   changes nothing about which rung runs.

Storage
-------
No new table and no new column. The confidence rides in llm_confidence_bp,
where every other model confidence already lives - integer basis points,
because a float must never enter a hash preimage. The structured body rides in
`details` behind a marker, so the line stays a sentence a human can read in the
audit trail while remaining machine-readable underneath. JSON is serialized
with sorted keys and no whitespace, so the same recommendation produces the
same bytes and therefore the same entry hash on any machine.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from app.config import CONFIDENCE_THRESHOLD
from app.models import AuditTrailEntry, PaymentFailureRecord
from app.policy import ATTEMPT_LADDER
from app.schemas import FailureClass
from app.state_machine import log_audit

# One ledger action, distinct from FAILURE_DIAGNOSED_LLM on purpose.
#
# The two say different things. FAILURE_DIAGNOSED_LLM records that a diagnosis
# was accepted and used to classify the record; this records what the model
# recommended, whether or not it was accepted. Keeping them separate is also
# what stops the advisory entry from leaking into safety_guard's confidence
# check, which reads FAILURE_DIAGNOSED_LLM alone - a reporting feature must not
# quietly change what the guard blocks.
ADVISORY_ACTION = "AI_RECOVERY_RECOMMENDATION"
ADVISORY_ACTOR = "llm_agent"

# Printed on every entry and returned by every API that serves one. A reader
# who sees only this line should still know the model did not act.
ADVISORY_BANNER = "AI ADVISORY - POLICY/GUARDRAILS CONTROL EXECUTION"

# The structured body follows this marker on its own line.
ADVISORY_MARKER = "AI_RECOMMENDATION_JSON="

# Failure class -> the channel the deterministic ladder would open with.
#
# This is the entire mechanism by which a recommendation acquires a channel,
# and it is worth being precise about what it means: the model is not asked
# which channel to use and could not answer if it were. It is asked what went
# wrong. The channel shown beside its answer is what policy.py would do first
# for that class - so the "recommendation" is really "here is what this
# diagnosis implies under the rules we already have".
#
# HARD_DECLINE's ladder is empty, so a compliance halt recommends nothing at
# all, which is the correct advice.
RECOMMENDED_CHANNEL_BY_CLASS = {
    failure_class: (rungs[0] if rungs else None)
    for failure_class, rungs in ATTEMPT_LADDER.items()
}

VALID_FAILURE_CLASSES = frozenset(c.value for c in FailureClass)

# SQLite caps a statement at 999 bound parameters; the bulk read binds one per
# payment id.
ID_CHUNK = 400


@dataclass(frozen=True)
class Recommendation:
    """
    One structured reading of one failure.

    Frozen, and deliberately not a PolicyDecision. The two are different kinds
    of object and the type system is the first thing keeping them apart: the
    safety guard's opening check is `isinstance(decision, PolicyDecision)`, so
    handing it one of these is refused before any field is read.
    """

    payment_id: str
    failure_class: str
    interpretation: str
    recommended_channel: Optional[str]
    model_suggested_action: str
    confidence: float
    rationale: str
    evidence: dict = field(default_factory=dict)
    review_required: bool = False

    # Not a parameter. A recommendation is advisory by construction, and the
    # flag exists so that every consumer - the API, the dashboard, a reviewer
    # reading raw JSON out of the ledger - is told so without having to know
    # this module exists.
    @property
    def advisory(self) -> bool:
        return True

    def to_dict(self) -> dict:
        return {
            "payment_id": self.payment_id,
            "failure_class": self.failure_class,
            "interpretation": self.interpretation,
            "recommended_channel": self.recommended_channel,
            "model_suggested_action": self.model_suggested_action,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "evidence": self.evidence,
            "review_required": self.review_required,
            "advisory": True,
        }


def evidence_from(record: PaymentFailureRecord) -> dict:
    """
    The facts the model was shown, taken off the record.

    Evidence has to be checkable, so this is drawn from the payment rather than
    from the model's answer: a reviewer can compare these five fields against
    the webhook Razorpay actually sent. They are exactly the fields
    llm_agent.diagnosis_inputs puts in the prompt, which is what makes them
    evidence rather than decoration.
    """
    return {
        "error_reason": record.error_reason,
        "error_description": record.error_description,
        "error_source": record.error_source,
        "error_step": record.error_step,
        "method": record.method,
    }


def build(
    record: PaymentFailureRecord,
    diagnosis,
    *,
    threshold: float = CONFIDENCE_THRESHOLD,
) -> Recommendation:
    """
    Turn a FailureDiagnosis into a structured recommendation.

    Pure: no database, no side effects, nothing to undo. `review_required` is
    computed here rather than read from the model, because whether a reading is
    strong enough to rely on is this system's judgement, not the model's.
    """
    root_class = getattr(diagnosis, "root_cause_class", None)
    confidence = float(getattr(diagnosis, "confidence", 0.0) or 0.0)

    # An unrecognised class recommends nothing. llm_agent already degrades an
    # invented class to HARD_DECLINE at zero confidence, so this is defence in
    # depth for anything that constructs a diagnosis some other way.
    if root_class not in VALID_FAILURE_CLASSES:
        root_class = FailureClass.HARD_DECLINE.value
        confidence = 0.0

    channel = RECOMMENDED_CHANNEL_BY_CLASS.get(root_class)
    review_required = confidence < threshold or channel is None

    if channel is None:
        rationale = (
            f"Read as {root_class} at {confidence:.0%} confidence. No escalation "
            f"ladder exists for this class, so the recommendation is to take no "
            f"automated action and have a person look at it."
        )
    elif review_required:
        rationale = (
            f"Read as {root_class} at {confidence:.0%} confidence, below the "
            f"{threshold:.0%} threshold this system acts on. The ladder for "
            f"{root_class} would open with {channel}; the reading is recorded "
            f"for review rather than relied on."
        )
    else:
        rationale = (
            f"Read as {root_class} at {confidence:.0%} confidence, above the "
            f"{threshold:.0%} threshold. Under the existing escalation ladder "
            f"that class opens with {channel}, which is what the policy engine "
            f"will evaluate - it is not booked by this recommendation."
        )

    return Recommendation(
        payment_id=record.payment_id,
        failure_class=root_class,
        interpretation=str(getattr(diagnosis, "technical_explanation", "") or ""),
        recommended_channel=channel,
        model_suggested_action=str(getattr(diagnosis, "suggested_action", "") or ""),
        confidence=confidence,
        rationale=rationale,
        evidence=evidence_from(record),
        review_required=review_required,
    )


def _headline(recommendation: Recommendation) -> str:
    """The sentence a person reads in the audit trail, before the JSON."""
    channel = recommendation.recommended_channel or "no automated action"
    flag = " Flagged for human review." if recommendation.review_required else ""
    return (
        f"{ADVISORY_BANNER}. Model read this failure as "
        f"{recommendation.failure_class} at "
        f"{recommendation.confidence:.0%} confidence and points to {channel}. "
        f"Recorded, not executed: the policy engine and safety guard decide "
        f"independently and may refuse.{flag}"
    )


def record_recommendation(
    db: Session,
    record: PaymentFailureRecord,
    recommendation: Recommendation,
    llm_metadata: Optional[dict] = None,
) -> AuditTrailEntry:
    """
    Append the recommendation to the existing ledger.

    Zero cost, no state transition, no commit of its own - exactly like every
    other observational entry. The only thing that happens as a result of
    recording an opinion is that the opinion is on the chain.
    """
    body = json.dumps(recommendation.to_dict(), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)

    metadata = dict(llm_metadata or {})
    # The confidence written to the chain is the recommendation's own, so the
    # stored basis points and the stored JSON can never disagree.
    metadata["confidence"] = recommendation.confidence

    return log_audit(
        db, record,
        action=ADVISORY_ACTION,
        actor=ADVISORY_ACTOR,
        details=f"{_headline(recommendation)}\n{ADVISORY_MARKER}{body}",
        cost_paise=0,
        llm_metadata=metadata,
    )


def parse(details: Optional[str]) -> Optional[dict]:
    """
    Read a recommendation back out of a ledger entry's details.

    Returns None for anything that is not one, including a truncated or
    corrupted body. A recommendation that cannot be read is absent, never
    half-present: the callers render "no AI reading", which is honest, where a
    partial dict would put a plausible-looking gap on a dashboard.
    """
    if not details or ADVISORY_MARKER not in details:
        return None

    _, _, body = details.partition(ADVISORY_MARKER)
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None

    return parsed if isinstance(parsed, dict) else None


def _latest_entries(db: Session, payment_ids) -> dict:
    """The newest advisory entry per payment id, chunked for SQLite."""
    payment_ids = list(payment_ids)
    latest = {}

    for start in range(0, len(payment_ids), ID_CHUNK):
        chunk = payment_ids[start:start + ID_CHUNK]
        rows = (
            db.query(AuditTrailEntry)
            .filter(AuditTrailEntry.payment_id.in_(chunk),
                    AuditTrailEntry.action == ADVISORY_ACTION)
            .order_by(AuditTrailEntry.sequence_no)
            .all()
        )
        # Ascending, so the last write for a payment id wins. The ledger is
        # append-only, so a re-diagnosis adds rather than replaces and the
        # record's current reading is simply the most recent one.
        for row in rows:
            latest[row.payment_id] = row

    return latest


def latest_for(db: Session, payment_id: str) -> Optional[dict]:
    """This record's current AI reading, or None."""
    entry = (
        db.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == payment_id,
                AuditTrailEntry.action == ADVISORY_ACTION)
        .order_by(AuditTrailEntry.sequence_no.desc())
        .first()
    )
    return None if entry is None else parse(entry.details)


def latest_for_many(db: Session, payment_ids) -> dict:
    """
    {payment_id: recommendation} for every id that has one.

    One query per chunk rather than one per record: the dashboard asks this of
    a whole cohort, and 65 round trips to render a panel is not a panel worth
    having.
    """
    found = {}
    for payment_id, entry in _latest_entries(db, payment_ids).items():
        parsed = parse(entry.details)
        if parsed is not None:
            found[payment_id] = parsed
    return found


def cohort_insight(db: Session, records, limit: int = 6) -> dict:
    """
    What the model has read across one cohort, newest first.

    Scoped by being handed the cohort's records rather than querying for them,
    so this panel describes the same population as every other figure on the
    dashboard - the invariant the cohort scoping exists to hold.
    """
    ordered = [r.payment_id for r in records]
    entries = _latest_entries(db, ordered)

    recommendations = []
    review_required = 0
    for entry in sorted(entries.values(), key=lambda e: e.sequence_no, reverse=True):
        parsed = parse(entry.details)
        if parsed is None:
            continue
        if parsed.get("review_required"):
            review_required += 1
        recommendations.append(parsed)

    return {
        "advisory_only": True,
        "notice": ADVISORY_BANNER,
        "count": len(recommendations),
        "review_required": review_required,
        "recommendations": recommendations[:limit],
    }
