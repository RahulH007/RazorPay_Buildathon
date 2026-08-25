"""
RecoverOS Outcome Engine
Replaces `random.random() < base_rate` with an explicit counterfactual.

The old simulator decided recovery with a coin flip against a hardcoded class
rate. Nothing the agent did could move that number - change the channel, the
copy, or the guardrails and the result was identical. It measured the config
file.

Here, every customer carries a stated behaviour: whether they would have paid
on their own and when, and how likely they are to respond to each channel.
That makes two things possible which a coin flip cannot support:

  * **Determinism.** Draws come from SHA-256 of (payment_id, seed, purpose,
    attempt), not from a sequential RNG. The outcome for one record does not
    depend on how many records were processed before it, so results are stable
    across reordering, parallelism, and partial re-runs.

  * **Attribution.** Because "would they have paid anyway?" is defined data, a
    holdout group has a meaning. Lift is measurable rather than asserted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional

# How long after failure we keep watching before calling it unrecovered.
OBSERVATION_WINDOW_HOURS = 72

# Hours after failure that each ladder rung is attempted. Silent retries chase
# a transient bank fault quickly; customer outreach is slower and spaced out.
ATTEMPT_SCHEDULE_HOURS = {
    "silent_retry": [0.5, 2, 6, 12, 24],
    "whatsapp_link": [1, 24],
    "upi_resequence": [1, 24],
    "hinglish_voice": [26],
    "human_queue": [48],
}


def draw(payment_id: str, seed: int, purpose: str, attempt: int = 0) -> float:
    """
    A reproducible uniform draw in [0, 1) for one specific question.

    Keyed on the record rather than drawn from a stream, so the same record
    yields the same value no matter what else the batch is doing.
    """
    key = f"{payment_id}|{seed}|{purpose}|{attempt}".encode("utf-8")
    digest = hashlib.sha256(key).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


@dataclass
class Behaviour:
    """What a given customer would do, stated rather than sampled."""

    natural_recovery_hours: Optional[float]  # None = would never pay unprompted
    responds_to: dict                        # channel -> probability

    @classmethod
    def from_record(cls, record_data: dict) -> "Behaviour":
        raw = record_data.get("behavior") or {}
        return cls(
            natural_recovery_hours=raw.get("natural_recovery_at_hours"),
            responds_to=raw.get("responds_to") or {},
        )

    def recovers_unprompted(self, window_hours: float = OBSERVATION_WINDOW_HOURS) -> bool:
        """Would this customer have paid without us, inside the window?"""
        if self.natural_recovery_hours is None:
            return False
        return self.natural_recovery_hours <= window_hours


@dataclass
class AttemptResult:
    recovered: bool
    reason: str
    attributable: bool  # True only when the intervention caused the recovery


def attempt_outcome(
    payment_id: str,
    behaviour: Behaviour,
    channel: str,
    attempt_number: int,
    seed: int,
) -> AttemptResult:
    """
    Resolve one recovery attempt.

    Attribution is the subtle part. If the customer was going to pay before
    this attempt would even have landed, the payment is theirs, not ours -
    counting it as recovered revenue is how recovery tools overstate their
    value. Such a payment still counts as recovered; it just is not
    attributable.
    """
    schedule = ATTEMPT_SCHEDULE_HOURS.get(channel, [1])
    at_hours = schedule[min(attempt_number, len(schedule) - 1)]

    natural = behaviour.natural_recovery_hours
    if natural is not None and natural <= at_hours:
        return AttemptResult(
            recovered=True,
            reason=(
                f"Customer paid unprompted at +{natural:g}h, before the "
                f"{channel} attempt at +{at_hours:g}h. Recovered, but not "
                f"attributable to this system."
            ),
            attributable=False,
        )

    probability = behaviour.responds_to.get(channel, 0.0)
    if draw(payment_id, seed, f"respond:{channel}", attempt_number) < probability:
        return AttemptResult(
            recovered=True,
            reason=(
                f"Customer responded to {channel} at +{at_hours:g}h "
                f"(responsiveness {probability:.0%})."
            ),
            attributable=True,
        )

    return AttemptResult(
        recovered=False,
        reason=(
            f"No response to {channel} at +{at_hours:g}h "
            f"(responsiveness {probability:.0%})."
        ),
        attributable=False,
    )


def control_outcome(behaviour: Behaviour) -> AttemptResult:
    """
    Resolve an untreated holdout record.

    Nothing is sent, so the only question is whether this customer would have
    paid on their own. This is the baseline every treated result is measured
    against.
    """
    if behaviour.recovers_unprompted():
        return AttemptResult(
            recovered=True,
            reason=(
                f"Holdout control: customer paid unprompted at "
                f"+{behaviour.natural_recovery_hours:g}h with no contact from us."
            ),
            attributable=False,
        )
    return AttemptResult(
        recovered=False,
        reason=(
            f"Holdout control: no payment within the "
            f"{OBSERVATION_WINDOW_HOURS}h observation window, uncontacted."
        ),
        attributable=False,
    )


# --- Holdout assignment -----------------------------------------------------


def assign_holdout(
    records: list,
    seed: int,
    percent: int,
    contact_key=lambda r: r.get("customer", {}).get("phone", ""),
    class_key=lambda r: r.get("_failure_class", "UNKNOWN"),
) -> set:
    """
    Choose the control group, returning the set of held-out contact hashes.

    Two properties matter and neither is optional.

    **Assignment is per contact, not per payment.** One person with two failed
    payments must land wholly in one arm. Splitting them contaminates the lift
    estimate and, worse, means we contact someone whose other payment we are
    deliberately leaving alone.

    **Assignment is stratified by failure class.** With a batch this small,
    unstratified sampling can easily put zero - or half - of a six-record class
    into control, which would make any per-class number meaningless.
    """
    from app.consent import contact_hash

    by_class: dict[str, dict[str, None]] = {}
    for record in records:
        digest = contact_hash(contact_key(record))
        # dict rather than set: insertion order is stable, so the ranking below
        # does not depend on set iteration order.
        by_class.setdefault(class_key(record), {})[digest] = None

    held_out = set()
    for failure_class, contacts in sorted(by_class.items()):
        ranked = sorted(
            contacts,
            key=lambda d: hashlib.sha256(f"{d}|{seed}".encode()).hexdigest(),
        )
        take = round(len(ranked) * percent / 100)
        held_out.update(ranked[:take])

    return held_out


def is_held_out(phone: str, held_out: set) -> bool:
    from app.consent import contact_hash

    return contact_hash(phone) in held_out
