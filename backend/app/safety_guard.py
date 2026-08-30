"""
RecoverOS Safety Guard

The final authorization point between a policy decision and an action that can
reach a customer, a bank, or Razorpay.

The architecture this completes reads:

    AI diagnoses -> deterministic policy decides -> safety guard authorizes
    -> executor performs

Each arrow is a narrowing. Diagnosis produces a failure class and nothing else;
policy turns that class into a channel and an amount from tables written in
code; the guard re-derives both from those same tables and refuses anything
that does not match. A model can therefore influence *what kind of failure this
is believed to be*, and nothing further. It cannot name a channel, an amount, a
state transition, or an API call, because there is no parameter on this module
through which such a thing could arrive: `authorize` accepts a PolicyDecision
object and refuses anything else outright.

Why a second layer at all
-------------------------
event_adapter already holds live webhooks whose error.reason is not in
RULE_MAP. That gate works, but it is one `if` on one code path. A future caller
that reaches execute_recovery some other way - a retry worker, an admin
endpoint, a replay tool - would skip it entirely and never know. This module
sits at the single point every action must pass through, so the guarantee
belongs to the executor rather than to whoever remembered to check first.

The two layers are deliberately redundant. Redundancy is the point: the cost of
a duplicated check is one query, and the cost of a missed one is a real Payment
Link sent to a real stranger on the strength of a bank error string.

What a refusal is
-----------------
A refusal is an outcome, not a silence. It writes SAFETY_GUARD_BLOCKED to the
append-only ledger, makes no state transition, calls nothing, spends nothing,
and leaves the record exactly where it was so a person can pick it up. It
deliberately does NOT close the record: the guard's job is to withhold an
automatic action, not to decide the payment is unrecoverable.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app.classifier import RULE_MAP
from app.config import CONFIDENCE_THRESHOLD, CONFIDENCE_THRESHOLD_BP, MAX_RETRIES
from app.guardrails import count_attempts, would_breach_cac
from app.models import AuditTrailEntry, PaymentFailureRecord
from app.policy import (
    ATTEMPT_LADDER,
    CHANNEL_ACTION_COST_PAISE,
    PolicyDecision,
    ReasonCode,
)
from app.razorpay_client import LIVE_SOURCE, SYNTHETIC_SOURCE
from app.schemas import FailureClass
from app.state_machine import log_audit

# The ledger action and actor a refusal is recorded under. A distinct actor
# from "policy_engine": a reviewer asking "who stopped this?" should not have to
# read the details field to find out which layer it was.
BLOCKED_ACTION = "SAFETY_GUARD_BLOCKED"
GUARD_ACTOR = "safety_guard"

# Written by event_adapter's unmapped-reason gate. Its presence means a human
# has been asked to look at this record, and an automatic action must not
# overtake that request.
HELD_FOR_REVIEW_ACTION = "UNMAPPED_REASON_HELD_FOR_REVIEW"

# Every channel any escalation ladder can propose. Derived from ATTEMPT_LADDER
# rather than retyped, so a rung added to policy cannot appear without the
# guard knowing the name. Deliberately NOT imported from
# recovery_actions.CHANNEL_ACTION_MAP - that module imports this one, and the
# guard must not depend on the thing it guards. tests/test_safety_guard.py
# asserts the two sets agree.
ALLOWED_CHANNELS = frozenset(
    channel for rungs in ATTEMPT_LADDER.values() for channel in rungs
)

# The states an automated recovery attempt may be made from. INGESTED is absent
# because nothing should act before diagnosis; the two terminal states are
# absent because nothing should act after one.
ACTIONABLE_STATES = frozenset({"DIAGNOSED", "INTERVENING"})
TERMINAL_STATES = frozenset({"RECOVERED", "FAILED_STOPPED"})

VALID_FAILURE_CLASSES = frozenset(c.value for c in FailureClass)

# Ledger actions whose llm_confidence_bp describes *the diagnosis of this
# failure*. CUSTOMER_REPLY_PARSED is excluded on purpose: it scores how well a
# model read a customer's message, which is a different question, and inbound.py
# already escalates on a weak reading. Treating it as diagnosis confidence would
# let an ambiguous WhatsApp reply block the next rung of a ladder.
DIAGNOSIS_CONFIDENCE_ACTIONS = ("FAILURE_DIAGNOSED_LLM",)


class GuardCode:
    """Why authorization was granted or refused. Recorded verbatim."""

    ALLOWED = "ALLOWED"
    NOT_A_POLICY_DECISION = "NOT_A_POLICY_DECISION"
    SOURCE_NOT_PERMITTED = "SOURCE_NOT_PERMITTED"
    UNKNOWN_CHANNEL = "UNKNOWN_CHANNEL"
    UNCLASSIFIED = "UNCLASSIFIED"
    CLASS_CHANNEL_MISMATCH = "CLASS_CHANNEL_MISMATCH"
    TERMINAL_STATE = "TERMINAL_STATE"
    INVALID_STATE = "INVALID_STATE"
    UNMAPPED_REASON = "UNMAPPED_REASON"
    HELD_FOR_REVIEW = "HELD_FOR_REVIEW"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    ATTEMPT_LIMIT = "ATTEMPT_LIMIT"
    STALE_DECISION = "STALE_DECISION"
    COST_MISMATCH = "COST_MISMATCH"
    SPEND_LIMIT = "SPEND_LIMIT"


@dataclass(frozen=True)
class GuardVerdict:
    """The guard's answer. Frozen: a verdict is evidence, not a working value."""

    allowed: bool
    code: str
    reason: str

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "code": self.code, "reason": self.reason}


_ALLOWED = GuardVerdict(
    allowed=True,
    code=GuardCode.ALLOWED,
    reason="Policy decision matches the deterministic channel, cost and state "
           "rules for this record.",
)


def _refuse(code: str, reason: str) -> GuardVerdict:
    return GuardVerdict(allowed=False, code=code, reason=reason)


def reason_is_recognized(record: PaymentFailureRecord, source: str) -> bool:
    """
    Whether this record's error.reason is approved for automatic recovery.

    RULE_MAP is that approval list: a human decided each entry maps to a class
    the system may act on. The question is only asked of live records, because
    the seeded dataset deliberately contains codes the rule engine does not
    know - they exist to exercise the model's slow path - and holding them
    would change what the simulator measures rather than protect anyone.
    """
    if source != LIVE_SOURCE:
        return True
    return record.error_reason in RULE_MAP


def _diagnosis_confidence_bp(db: Session, record: PaymentFailureRecord) -> Optional[int]:
    """
    The most recent recorded confidence in this record's diagnosis, or None.

    None means the rule engine classified it - a deterministic lookup has no
    confidence to report, and the absence is not a weakness to be penalised.
    """
    entry = (
        db.query(AuditTrailEntry)
        .filter(
            AuditTrailEntry.payment_id == record.payment_id,
            AuditTrailEntry.action.in_(DIAGNOSIS_CONFIDENCE_ACTIONS),
            AuditTrailEntry.llm_confidence_bp.isnot(None),
        )
        .order_by(AuditTrailEntry.sequence_no.desc())
        .first()
    )
    return None if entry is None else entry.llm_confidence_bp


def _is_held_for_review(db: Session, record: PaymentFailureRecord) -> bool:
    return (
        db.query(AuditTrailEntry)
        .filter(
            AuditTrailEntry.payment_id == record.payment_id,
            AuditTrailEntry.action == HELD_FOR_REVIEW_ACTION,
        )
        .first()
        is not None
    )


def authorize(
    db: Session,
    record: PaymentFailureRecord,
    decision,
    *,
    source: str,
) -> GuardVerdict:
    """
    Decide whether this policy decision may be executed.

    Pure with respect to state: it reads the record and the ledger, writes
    nothing, commits nothing and touches no network. The writing half is
    `block`, so the only thing that can change as a result of asking is
    nothing.

    Checks run cheapest-and-most-fundamental first and the first refusal wins,
    exactly as in policy.decide_next_action, so the recorded code names the
    deepest reason rather than whichever happened to be evaluated last.
    """
    # 1. Provenance. The single most important check in this module: an action
    #    may only be executed on the strength of an object the deterministic
    #    policy engine built. A dict, a model's JSON, or a PolicyDecision
    #    carrying any reason code other than PROCEED is not a decision to act.
    if not isinstance(decision, PolicyDecision):
        return _refuse(
            GuardCode.NOT_A_POLICY_DECISION,
            f"Execution was proposed with a {type(decision).__name__}, not a "
            f"PolicyDecision produced by the policy engine. Only the "
            f"deterministic policy engine may authorise an action.",
        )

    if decision.should_act is not True or decision.reason_code != ReasonCode.PROCEED:
        return _refuse(
            GuardCode.NOT_A_POLICY_DECISION,
            f"PolicyDecision does not approve action "
            f"(should_act={decision.should_act!r}, "
            f"reason_code={decision.reason_code!r}). Only "
            f"{ReasonCode.PROCEED} authorises execution.",
        )

    # 2. Source. The record itself carries where it came from, and a caller may
    #    not upgrade it: this is what stops a synthetic record being executed
    #    down the live path even with real credentials loaded.
    record_source = record.source or SYNTHETIC_SOURCE
    if source not in (LIVE_SOURCE, SYNTHETIC_SOURCE):
        return _refuse(
            GuardCode.SOURCE_NOT_PERMITTED,
            f"Unrecognised execution source {source!r}. Permitted sources are "
            f"{LIVE_SOURCE!r} and {SYNTHETIC_SOURCE!r}.",
        )
    if source != record_source:
        return _refuse(
            GuardCode.SOURCE_NOT_PERMITTED,
            f"Execution source {source!r} does not match the record's own "
            f"source {record_source!r}. A record may only be acted on down the "
            f"path it arrived by.",
        )

    # 3. Channel allowlist.
    if decision.channel not in ALLOWED_CHANNELS:
        return _refuse(
            GuardCode.UNKNOWN_CHANNEL,
            f"Proposed channel {decision.channel!r} is not one this system "
            f"knows how to perform. Allowed: "
            f"{', '.join(sorted(ALLOWED_CHANNELS))}.",
        )

    # 4. The record must actually be classified.
    failure_class = record.failure_class
    if failure_class not in VALID_FAILURE_CLASSES:
        return _refuse(
            GuardCode.UNCLASSIFIED,
            f"Record carries failure_class={failure_class!r}, which is not one "
            f"of the five recognised classes. Nothing may be executed against "
            f"an unclassified payment.",
        )

    # 5. Is this channel a legitimate step for this class? The ladder is the
    #    only place that answers, and HARD_DECLINE's ladder is empty, so a
    #    compliance halt can never be paired with any channel at all.
    ladder = ATTEMPT_LADDER.get(failure_class, [])
    if decision.channel not in ladder:
        return _refuse(
            GuardCode.CLASS_CHANNEL_MISMATCH,
            f"Channel {decision.channel!r} is not a step in the escalation "
            f"ladder for {failure_class} "
            f"({' -> '.join(ladder) if ladder else 'no ladder - no outreach'}). "
            f"The proposed action does not fit the diagnosed failure.",
        )

    # 6. State. No action after a payment is settled, and none before it is
    #    diagnosed.
    state = record.recovery_state
    if state in TERMINAL_STATES:
        return _refuse(
            GuardCode.TERMINAL_STATE,
            f"Record is already {state}. No recovery action may be taken "
            f"against a payment that has reached a terminal state.",
        )
    if state not in ACTIONABLE_STATES:
        return _refuse(
            GuardCode.INVALID_STATE,
            f"Record is in state {state!r}. An automated attempt may only be "
            f"made from {' or '.join(sorted(ACTIONABLE_STATES))}.",
        )

    # 7. Approved vocabulary, on the live path only.
    if not reason_is_recognized(record, source):
        return _refuse(
            GuardCode.UNMAPPED_REASON,
            f"error.reason={record.error_reason!r} arrived from a live "
            f"Razorpay webhook and is not in RULE_MAP, the set of codes "
            f"approved for automatic recovery. The diagnosis may be correct; "
            f"nobody has decided this system should spend money and message a "
            f"stranger on the strength of a code it has never been told how to "
            f"treat.",
        )

    # 8. A record already queued for a person is not available to automation.
    if _is_held_for_review(db, record):
        return _refuse(
            GuardCode.HELD_FOR_REVIEW,
            f"Record was held for human review "
            f"({HELD_FOR_REVIEW_ACTION}). An automated action must not "
            f"overtake a request for a person to look at it.",
        )

    # 9. Confidence, where a model produced the diagnosis. The classifier
    #    already escalates below the threshold, so this is a second reading of
    #    the same rule at the point where money would actually be spent.
    confidence_bp = _diagnosis_confidence_bp(db, record)
    if confidence_bp is not None and confidence_bp < CONFIDENCE_THRESHOLD_BP:
        return _refuse(
            GuardCode.LOW_CONFIDENCE,
            f"Diagnosis confidence {confidence_bp / 10000:.2f} is below the "
            f"{CONFIDENCE_THRESHOLD} threshold. An uncertain reading of a bank "
            f"error is not grounds for contacting a customer.",
        )

    # 10 / 11. Attempts. The cap is re-checked against history as it stands
    #    now, and the decision's own view of that history must agree: a
    #    decision computed against a different attempt count was made about a
    #    record in a state that no longer exists.
    attempts = count_attempts(db, record)
    if attempts >= MAX_RETRIES:
        return _refuse(
            GuardCode.ATTEMPT_LIMIT,
            f"{attempts} attempts already made against this payment, at a cap "
            f"of {MAX_RETRIES}.",
        )
    if decision.attempt_number != attempts:
        return _refuse(
            GuardCode.STALE_DECISION,
            f"Policy decision was computed at attempt "
            f"{decision.attempt_number} but the ledger now records {attempts}. "
            f"A decision about a record's earlier state must not be executed "
            f"against its current one.",
        )

    # 12. The amount. Re-derived from the deterministic table rather than taken
    #     from the decision, so no caller - and nothing a model produced - can
    #     put a different number into the ledger or into a spend calculation.
    expected_cost = CHANNEL_ACTION_COST_PAISE.get(decision.channel)
    if expected_cost is None or decision.cost_paise != expected_cost:
        return _refuse(
            GuardCode.COST_MISMATCH,
            f"Proposed cost {decision.cost_paise}p for {decision.channel!r} "
            f"does not match the {expected_cost}p this system charges for that "
            f"channel. The amount is a property of the channel, never of the "
            f"proposal.",
        )

    # 13. And the ceiling, re-verified rather than trusted.
    if would_breach_cac(db, record, decision.cost_paise):
        return _refuse(
            GuardCode.SPEND_LIMIT,
            f"Spending a further {decision.cost_paise}p would take this "
            f"payment past its cost ceiling.",
        )

    return _ALLOWED


def _proposal(decision) -> str:
    """Describe what was refused, defensively - `decision` may be anything."""
    if isinstance(decision, PolicyDecision):
        return (
            f"channel={decision.channel!r}, cost={decision.cost_paise}p, "
            f"attempt={decision.attempt_number}"
        )
    return f"proposal={type(decision).__name__}: {str(decision)[:120]}"


def block(
    db: Session,
    record: PaymentFailureRecord,
    decision,
    verdict: GuardVerdict,
) -> dict:
    """
    Record a refusal and return the executor's result.

    Called only when `authorize` refused. It writes one ledger entry and does
    nothing else: no state transition, no channel, no API call, no spend. The
    record is left where it was, because withholding an automatic action is not
    the same decision as declaring the payment unrecoverable.

    The returned `action` is "declined" rather than a verb of its own. Callers
    that walk the escalation ladder already stop on a decline, so a refusal
    ends the loop for the right reason without every caller having to learn a
    new one; `reason_code` and `guard_code` say which layer refused.
    """
    log_audit(
        db, record,
        action=BLOCKED_ACTION,
        actor=GUARD_ACTOR,
        details=(
            f"WHY_WE_DIDNT_ACT: {verdict.code}: {verdict.reason} "
            f"Refused proposal: {_proposal(decision)}, "
            f"class={record.failure_class!r}, state={record.recovery_state!r}, "
            f"error.reason={record.error_reason!r}, source={record.source!r}. "
            f"No channel was used, no external call was made and nothing was "
            f"spent."
        ),
        cost_paise=0,
    )

    return {
        "action": "declined",
        "payment_id": record.payment_id,
        "failure_class": record.failure_class,
        "should_act": False,
        "reason_code": BLOCKED_ACTION,
        "guard_code": verdict.code,
        "reason": verdict.reason,
        "channel": getattr(decision, "channel", None),
        "attempt_number": getattr(decision, "attempt_number", 0),
        "cost_paise": 0,
        "customer_contacted": False,
    }
