"""
RecoverOS Policy Engine
Decides whether to act, on which channel, and when to stop.

This is the layer the previous design lacked. Routing was a static lookup:
error code picked a failure class, failure class picked a channel, and
everything that was not a hard decline got contacted exactly once. There was
no eligibility question and no second attempt, which meant MAX_RETRIES was
unreachable and the CAC ceiling never bound.

Every decision here - including every refusal - returns a reason code and is
written to the ledger. Restraint is an output of this system, not an absence
of one, and it should be as auditable as a recovery.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config import (
    CHANNEL_COSTS_PAISE,
    MAX_RETRIES,
    MERCHANT_MARGIN_PERCENT,
    RECOVERY_RATES,
)
from app.consent import is_suppressed
from app.guardrails import (
    cac_ceiling_paise,
    count_attempts,
    spend_paise,
    would_breach_cac,
)
from app.models import PaymentFailureRecord


class ReasonCode:
    """Why an action was or was not taken. Recorded verbatim in the ledger."""

    PROCEED = "PROCEED"
    HARD_DECLINE = "HARD_DECLINE"
    RETRY_CAP_REACHED = "RETRY_CAP_REACHED"
    LADDER_EXHAUSTED = "LADDER_EXHAUSTED"
    CAC_CEILING = "CAC_CEILING"
    CONSENT_WITHDRAWN = "CONSENT_WITHDRAWN"
    QUIET_HOURS_DEFERRED = "QUIET_HOURS_DEFERRED"
    NEGATIVE_EXPECTED_VALUE = "NEGATIVE_EXPECTED_VALUE"
    HOLDOUT_CONTROL = "HOLDOUT_CONTROL"


# Which channel each step of the escalation uses, per failure class.
#
# The ladder is what makes MAX_RETRIES reachable at all: a single-shot design
# can never reach a cap of three. Steps escalate in cost, so the cheap channel
# is always tried before the expensive one.
ATTEMPT_LADDER = {
    # Silent retry is free and never touches the customer, so nothing in the
    # ladder itself stops it - MAX_RETRIES is the binding constraint. The
    # ladder is deliberately longer than the cap so the cap is what fires.
    "TRANSIENT_TECHNICAL": ["silent_retry"] * 5,
    "AUTH_FRICTION": ["whatsapp_link", "whatsapp_link"],
    "MANDATE_BALANCE": ["upi_resequence", "whatsapp_link"],
    "B2B_RECEIVABLE": ["whatsapp_link", "hinglish_voice", "human_queue"],
    "HARD_DECLINE": [],
}

# The consent channel each recovery channel maps to. Silent retry and the
# human queue are absent because neither sends the customer anything.
CHANNEL_CONSENT_MAP = {
    "whatsapp_link": "whatsapp",
    "upi_resequence": "whatsapp",
    "hinglish_voice": "voice",
}

# Per-action cost, keyed by channel rather than failure class, because one
# class can now use several channels as it escalates.
CHANNEL_ACTION_COST_PAISE = {
    "silent_retry": CHANNEL_COSTS_PAISE["TRANSIENT_TECHNICAL"],
    "whatsapp_link": CHANNEL_COSTS_PAISE["AUTH_FRICTION"],
    "upi_resequence": CHANNEL_COSTS_PAISE["MANDATE_BALANCE"],
    "hinglish_voice": CHANNEL_COSTS_PAISE["B2B_RECEIVABLE"],
    "human_queue": 0,
}


@dataclass
class PolicyDecision:
    """The outcome of one decision, whether or not it results in an action."""

    should_act: bool
    reason_code: str
    reason: str
    channel: Optional[str] = None
    attempt_number: int = 0
    cost_paise: int = 0

    def to_dict(self) -> dict:
        return {
            "should_act": self.should_act,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "channel": self.channel,
            "attempt_number": self.attempt_number,
            "cost_paise": self.cost_paise,
        }


def expected_value_paise(record: PaymentFailureRecord) -> int:
    """
    What one more successful recovery is worth to the merchant, in paise.

    Gross GMV is the wrong number: recovering Rs 1,000 of revenue is not worth
    Rs 1,000 to the merchant, it is worth the margin on it. The assumption is
    stated explicitly in config rather than buried, because it drives whether
    we spend money.
    """
    rate = RECOVERY_RATES.get(record.failure_class, 0.0)
    return int(record.amount * rate * MERCHANT_MARGIN_PERCENT / 100)


def decide_next_action(
    db: Session,
    record: PaymentFailureRecord,
    now: Optional[datetime] = None,
    is_holdout: bool = False,
) -> PolicyDecision:
    """
    Decide the next step for this record.

    Checks run cheapest-first, and the first refusal wins, so the recorded
    reason is the most fundamental one rather than whichever happened to be
    evaluated last.
    """
    failure_class = record.failure_class
    attempts = count_attempts(db, record)

    # 1. Hard decline - never contact, at any cost.
    if failure_class == "HARD_DECLINE":
        return PolicyDecision(
            should_act=False,
            reason_code=ReasonCode.HARD_DECLINE,
            reason=(
                f"Hard decline ({record.error_reason}). Zero retries, zero "
                f"customer outreach. This is a compliance-mandated halt, not a "
                f"system failure."
            ),
            attempt_number=attempts,
        )

    # 2. Holdout - the control arm is never contacted, which is what makes the
    #    recovery number causal rather than merely correlated.
    if is_holdout:
        return PolicyDecision(
            should_act=False,
            reason_code=ReasonCode.HOLDOUT_CONTROL,
            reason=(
                "Assigned to the holdout control group. Left untreated so that "
                "recovery attributable to this system can be measured against a "
                "baseline."
            ),
            attempt_number=attempts,
        )

    ladder = ATTEMPT_LADDER.get(failure_class, [])
    if not ladder:
        return PolicyDecision(
            should_act=False,
            reason_code=ReasonCode.LADDER_EXHAUSTED,
            reason=f"No escalation ladder defined for class {failure_class}",
            attempt_number=attempts,
        )

    # 3. Attempt cap.
    if attempts >= MAX_RETRIES:
        return PolicyDecision(
            should_act=False,
            reason_code=ReasonCode.RETRY_CAP_REACHED,
            reason=(
                f"Attempt cap reached: {attempts} of a maximum {MAX_RETRIES} "
                f"attempts already made in this batch."
            ),
            attempt_number=attempts,
        )

    # 4. Ladder exhausted (may be shorter than the global cap).
    if attempts >= len(ladder):
        return PolicyDecision(
            should_act=False,
            reason_code=ReasonCode.LADDER_EXHAUSTED,
            reason=(
                f"Escalation ladder for {failure_class} is exhausted after "
                f"{len(ladder)} step(s): {' -> '.join(ladder)}."
            ),
            attempt_number=attempts,
        )

    channel = ladder[attempts]
    cost = CHANNEL_ACTION_COST_PAISE.get(channel, 0)

    # 5. Would this spend breach the cost ceiling?
    if would_breach_cac(db, record, cost):
        spent = spend_paise(db, record)
        ceiling = cac_ceiling_paise(record)
        return PolicyDecision(
            should_act=False,
            reason_code=ReasonCode.CAC_CEILING,
            reason=(
                f"Spending {cost}p on {channel} would take total spend to "
                f"{spent + cost}p against a ceiling of {ceiling}p "
                f"(15% of Rs {record.amount / 100:,.2f}). Not worth recovering "
                f"at this price."
            ),
            channel=channel,
            attempt_number=attempts,
            cost_paise=cost,
        )

    # 6. Is the action worth more than it costs?
    expected = expected_value_paise(record)
    if cost > 0 and cost > expected:
        return PolicyDecision(
            should_act=False,
            reason_code=ReasonCode.NEGATIVE_EXPECTED_VALUE,
            reason=(
                f"{channel} costs {cost}p but the expected margin recovered is "
                f"only {expected}p (success rate "
                f"{RECOVERY_RATES.get(failure_class, 0):.0%} on "
                f"Rs {record.amount / 100:,.2f} at {MERCHANT_MARGIN_PERCENT}% "
                f"margin). Contacting this customer destroys value."
            ),
            channel=channel,
            attempt_number=attempts,
            cost_paise=cost,
        )

    # 7. Consent and quiet hours, for channels that actually reach a person.
    consent_channel = CHANNEL_CONSENT_MAP.get(channel)
    if consent_channel:
        suppressed, reason = is_suppressed(
            db, record.customer_phone, consent_channel, now
        )
        if suppressed:
            code = (
                ReasonCode.QUIET_HOURS_DEFERRED
                if "QUIET_HOURS" in (reason or "")
                else ReasonCode.CONSENT_WITHDRAWN
            )
            return PolicyDecision(
                should_act=False,
                reason_code=code,
                reason=reason,
                channel=channel,
                attempt_number=attempts,
                cost_paise=cost,
            )

    return PolicyDecision(
        should_act=True,
        reason_code=ReasonCode.PROCEED,
        reason=(
            f"Attempt {attempts + 1} of {len(ladder)} for {failure_class}: "
            f"{channel} at {cost}p, within the {cac_ceiling_paise(record)}p "
            f"ceiling and worth an expected {expected}p."
        ),
        channel=channel,
        attempt_number=attempts,
        cost_paise=cost,
    )
