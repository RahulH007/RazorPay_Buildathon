"""
RecoverOS Expected Recovery Value
Is this attempt worth making, before it is made?

The policy engine already refused actions costing more than the margin they
could recover, using a flat per-class rate from config. That check is a good
one and is untouched. What it cannot do is notice that *this* channel has been
tried on *this* customer four times and never once been paid: the flat rate
says AUTH_FRICTION recovers 40% of the time, so a fifth WhatsApp message keeps
looking worthwhile forever.

ERV values the specific attempt:

    expected_value = amount x observed success probability
    expected_net   = expected_value - action cost

and refuses when expected_net <= 0. Both sides are integer paise: a WhatsApp
send costs 50 paise, not Rs 50, and every worked example in this repository is
stated in those units. Break-even is a refusal, not an approval:
an attempt that only matches its own cost in expectation has spent real money
and real customer patience for nothing.

Where the probability comes from
--------------------------------
Existing data, in order of how specific it is, and always labelled:

    customer_history   this contact's own outcomes on this channel, once there
                       are enough of them to be a rate rather than a coin-flip
    channel_history    this channel's outcomes across every record
    default_estimate   config.RECOVERY_RATES - the flat per-class rate that was
                       always there, marked as an estimate, not an observation

Both history sources come from intervention_economics.by_intervention, reused
unchanged, so "this channel works" means the same thing here as it does on the
dashboard: a recovery is credited to the last attempt before it. There is no
model here, and there is nothing to train.

Integer arithmetic
------------------
Probability is basis points and value is paise, because these numbers reach the
ledger's hash preimage through the decision's reason text, and float arithmetic
is not reproducible across runtimes. Same rule as cost_paise and
llm_confidence_bp everywhere else in this system.

What this is not
----------------
It is one more deterministic constraint, evaluated last, after every existing
policy rule. A compliance halt, a spend ceiling or an exhausted ladder must
never be reported as an economic stop, because the reason code is what an
operator acts on and the most fundamental reason has to be the one that
survives. Approval here is not authorisation either: the safety guard runs
afterwards and can still refuse.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from app import ledger
from app.config import RECOVERY_RATES
from app.intervention_economics import by_intervention
from app.models import PaymentFailureRecord

# How much evidence before an observation beats the default.
#
# Two attempts is not a rate. Letting one customer's coin-flip drive a spend
# decision is how a system talks itself into stopping recovery on someone who
# simply had a bad fortnight, so the customer threshold is deliberately above
# the point where a single outcome swings the answer.
MIN_CUSTOMER_ATTEMPTS = 3
MIN_CHANNEL_ATTEMPTS = 20

BASIS_POINTS = 10_000

# How each rung reads to a person. Display only - the machine-readable channel
# name travels alongside it in every payload.
CHANNEL_LABELS = {
    "silent_retry": "Silent Retry",
    "whatsapp_link": "WhatsApp Link",
    "upi_resequence": "UPI Resequence",
    "hinglish_voice": "Hinglish Voice Call",
    "human_queue": "Human Escalation",
}


class ProbabilitySource:
    """Where the number came from. Reported on every estimate."""

    CUSTOMER_HISTORY = "customer_history"
    CHANNEL_HISTORY = "channel_history"
    DEFAULT_ESTIMATE = "default_estimate"


OBSERVED_SOURCES = frozenset(
    {ProbabilitySource.CUSTOMER_HISTORY, ProbabilitySource.CHANNEL_HISTORY}
)


@dataclass(frozen=True)
class ErvEstimate:
    """One channel, one record, valued. Frozen: an estimate is evidence."""

    payment_id: str
    channel: str
    amount_paise: int
    probability_bp: int
    probability_source: str
    probability_basis: str
    expected_value_paise: int
    cost_paise: int
    expected_net_paise: int

    @property
    def observed(self) -> bool:
        """True when the probability came from outcomes, not from an assumption."""
        return self.probability_source in OBSERVED_SOURCES

    @property
    def viable(self) -> bool:
        return self.expected_net_paise > 0

    def to_dict(self) -> dict:
        return {
            "payment_id": self.payment_id,
            "channel": self.channel,
            "channel_label": CHANNEL_LABELS.get(self.channel, self.channel),
            "amount_paise": self.amount_paise,
            "probability_bp": self.probability_bp,
            "probability_percent": self.probability_bp / 100,
            "probability_source": self.probability_source,
            "probability_basis": self.probability_basis,
            "observed": self.observed,
            "expected_value_paise": self.expected_value_paise,
            "cost_paise": self.cost_paise,
            "expected_net_paise": self.expected_net_paise,
            "viable": self.viable,
            "trace": trace_lines(self),
        }


# --- Probability ------------------------------------------------------------


def _channel_stats(db: Session) -> dict:
    """
    Every channel's attempts and recoveries across the whole database.

    Memoized on the session and keyed on the ledger head. The chain is
    append-only, so while the head is unchanged no outcome already counted can
    have changed - which makes the head a sound cache key and stops a 65-record
    batch walking the whole ledger 65 times.
    """
    head = ledger.get_head(db)
    key = head.entry_hash if head else None

    cached = db.info.get("erv_channel_stats")
    if cached is not None and cached[0] == key:
        return cached[1]

    records = db.query(PaymentFailureRecord).all()
    stats = {
        name: {"attempts": row["attempts"], "recovered": row["recovered"]}
        for name, row in by_intervention(db, records)["interventions"].items()
    }
    db.info["erv_channel_stats"] = (key, stats)
    return stats


def _customer_stats(db: Session, record: PaymentFailureRecord) -> dict:
    """This contact's own outcomes per channel, excluding the record itself."""
    # Imported here rather than at module scope: customer_profile imports
    # ai_advisor, which imports policy, which imports this module.
    from app.customer_profile import build_profile

    return build_profile(db, record).channels


def estimate_probability(
    db: Session,
    record: PaymentFailureRecord,
    channel: str,
) -> tuple:
    """
    (probability_bp, source, basis) for this channel on this record.

    Most specific evidence first, falling back until something qualifies. The
    basis string always names the counts it came from, so a reader can
    recompute the number rather than take it on trust.
    """
    customer = _customer_stats(db, record).get(channel)
    if customer and customer["attempts"] >= MIN_CUSTOMER_ATTEMPTS:
        bp = customer["recovered"] * BASIS_POINTS // customer["attempts"]
        return bp, ProbabilitySource.CUSTOMER_HISTORY, (
            f"{customer['recovered']} of {customer['attempts']} previous "
            f"{channel} attempts on this contact were recovered."
        )

    channel_wide = _channel_stats(db).get(channel)
    if channel_wide and channel_wide["attempts"] >= MIN_CHANNEL_ATTEMPTS:
        bp = channel_wide["recovered"] * BASIS_POINTS // channel_wide["attempts"]
        return bp, ProbabilitySource.CHANNEL_HISTORY, (
            f"{channel_wide['recovered']} of {channel_wide['attempts']} "
            f"{channel} attempts across all records were recovered."
        )

    # The deterministic fallback that was always here. Labelled, so nobody
    # mistakes an assumption for a measurement.
    rate = RECOVERY_RATES.get(record.failure_class, 0.0)
    return int(rate * BASIS_POINTS), ProbabilitySource.DEFAULT_ESTIMATE, (
        f"Default estimate for {record.failure_class or 'an unclassified record'} "
        f"({rate:.0%}) - not observed. Insufficient history: fewer than "
        f"{MIN_CUSTOMER_ATTEMPTS} {channel} attempts on this contact and fewer "
        f"than {MIN_CHANNEL_ATTEMPTS} across all records."
    )


# --- Valuing ----------------------------------------------------------------


def evaluate(
    db: Session,
    record: PaymentFailureRecord,
    channel: str,
    cost_paise: int,
    probability_bp: Optional[int] = None,
) -> ErvEstimate:
    """
    Value one candidate action. Pure: reads only, writes nothing.

    `probability_bp` is an override for tests and for callers that have already
    estimated; production callers leave it out and get the labelled estimate.
    """
    if probability_bp is None:
        probability_bp, source, basis = estimate_probability(db, record, channel)
    else:
        source, basis = ProbabilitySource.DEFAULT_ESTIMATE, "supplied by the caller"

    expected_value = record.amount * probability_bp // BASIS_POINTS

    return ErvEstimate(
        payment_id=record.payment_id,
        channel=channel,
        amount_paise=record.amount,
        probability_bp=probability_bp,
        probability_source=source,
        probability_basis=basis,
        expected_value_paise=expected_value,
        cost_paise=cost_paise,
        expected_net_paise=expected_value - cost_paise,
    )


def _rupees(paise: int) -> str:
    """`Rs 3,049.50`, sign in front, from integer paise."""
    sign = "-" if paise < 0 else ""
    whole, part = divmod(abs(paise), 100)
    return f"{sign}Rs {whole:,}.{part:02d}"


def trace_lines(estimate: ErvEstimate) -> list:
    """The block a reviewer reads, in the order the arithmetic happens."""
    return [
        f"Payment: {_rupees(estimate.amount_paise)}",
        f"Action: {CHANNEL_LABELS.get(estimate.channel, estimate.channel)}",
        f"Estimated success: {estimate.probability_bp // 100}%"
        f"{'' if estimate.observed else ' (default estimate)'}",
        f"Expected recovery: {_rupees(estimate.expected_value_paise)}",
        f"Cost: {_rupees(estimate.cost_paise)}",
        f"Expected net: {_rupees(estimate.expected_net_paise)}",
        f"Decision: {'PROCEED' if estimate.viable else 'STOP - ECONOMICALLY UNVIABLE'}",
    ]


def trace(estimate: ErvEstimate) -> str:
    """The same block as one string, for the ledger's reason field."""
    return " | ".join(trace_lines(estimate)) + f" | Basis: {estimate.probability_basis}"
