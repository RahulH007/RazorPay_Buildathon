"""
RecoverOS Customer Recovery Profile
Why this customer, why this channel, why now.

The system could already say what went wrong and what it would do about it. It
could say nothing at all about the person on the other end, so a customer who
had ignored two WhatsApp links and paid twice after a voice call was offered a
third WhatsApp link, and nothing in the ledger showed that anyone had noticed.

Everything needed to notice was already stored. A payment carries a contact, a
method and an outcome; the chain records which intervention preceded each
recovery and the microsecond it settled. This module is a read over that,
keyed on the normalized phone number the consent registry already treats as a
customer's identity - so the same person written three ways is one history
rather than three.

Two rules run through all of it.

Nothing is invented
-------------------
Every line of evidence names a count that can be recomputed from the records it
came from. A customer with no history gets "No prior payments from this contact
in this system", not a confident sentence assembled from one data point, and
`sufficiency` says out loud which of those two situations a reader is in. Three
failed WhatsApp attempts with no recovery names no effective channel: that is a
habit of ours, not a preference of theirs.

Nothing is authorised
---------------------
This module cannot import anything that acts, and the channel it names is
constrained to rungs that already exist in policy.ATTEMPT_LADDER. It is
allowed to recommend a channel the ladder will not use for this record - that
is the point of a recommendation - and when it does, `overridden_by_policy`
says so and the executor follows the ladder regardless. An advisory nobody can
override is not an advisory.

Where the channel outcomes come from
------------------------------------
intervention_economics.by_intervention, unchanged, pointed at this customer's
own past records. The attribution rule is therefore identical to the one the
dashboard reports - a recovery is credited to the last attempt before it - so
"voice works for this customer" and "voice works overall" are the same
sentence measured the same way. That reuse is also the feedback loop: an
intervention that lands today is evidence tomorrow, with nothing written back.

Note on attribution: this reading is arithmetic over the customer's records,
not a model call, and it is recorded under its own actor for exactly that
reason. A ledger whose purpose is to say who did what must not credit a model
for counting.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app import ai_advisor
from app.ai_advisor import ADVISORY_BANNER, ADVISORY_MARKER
from app.config import IST, SETTLEMENT_TIMEOUT_MINUTES
from app.consent import contact_hash, in_quiet_hours, next_permitted_time, normalize_phone
from app.guardrails import ATTEMPT_ACTIONS
from app.intervention_economics import by_intervention
from app.models import AuditTrailEntry, PaymentFailureRecord
from app.policy import ATTEMPT_LADDER, CHANNEL_CONSENT_MAP
from app.state_machine import log_audit

ADVISORY_ACTION = "CUSTOMER_RECOVERY_ADVISORY"

# Not "llm_agent". See the note on attribution above.
ADVISORY_ACTOR = "profile_engine"

NO_HISTORY_EVIDENCE = "No prior payments from this contact in this system."

# How much history is enough to say anything, stated as constants so the
# thresholds are arguable rather than buried in a conditional.
#
# The unit is a *resolved* prior payment - one that reached RECOVERED. An open
# record proves nothing yet, and a record that failed proves the channel did
# not work, which is counted but never used to claim a preference.
MIN_RESOLVED_FOR_ADVICE = 1      # below this, no channel claim at all
MIN_RESOLVED_FOR_PREFERENCE = 2  # below this, a data point rather than a pattern
MIN_RECOVERIES_FOR_TIMING = 2    # one settlement is an anecdote, not an hour

# Confidence is a stated formula, not a judgement. A reader who disagrees with
# the numbers can see exactly which ones to argue with.
CONFIDENCE_BASE = 0.45
CONFIDENCE_PER_RESOLVED = 0.15
CONFIDENCE_CAP = 0.90

FOLLOW_UP_AFTER_MINUTES = SETTLEMENT_TIMEOUT_MINUTES

# Channels that reach a person by voice, and are therefore subject to the quiet
# hours the consent module already enforces. Derived from the consent map so a
# channel added to policy cannot silently escape the timing question.
VOICE_CHANNELS = frozenset(
    channel for channel, consent in CHANNEL_CONSENT_MAP.items() if consent == "voice"
)

LADDER_RUNGS = frozenset(c for rungs in ATTEMPT_LADDER.values() for c in rungs)


class Sufficiency:
    """How much of a claim this history can support."""

    NONE = "none"
    THIN = "thin"
    SUFFICIENT = "sufficient"


@dataclass(frozen=True)
class CustomerProfile:
    """What this system has actually seen from one contact, and nothing else."""

    contact_hash: str
    payments_seen: int
    recovered: int
    failed: int
    open_count: int
    methods: dict
    recovered_methods: dict
    channels: dict
    effective_channel: Optional[str]
    failure_reasons: dict
    failure_classes: dict
    recovery_hours_ist: list
    sufficiency: str
    sufficiency_reason: str

    def to_dict(self) -> dict:
        return {
            "contact_hash": self.contact_hash,
            "payments_seen": self.payments_seen,
            "recovered": self.recovered,
            "failed": self.failed,
            "open": self.open_count,
            "methods": self.methods,
            "recovered_methods": self.recovered_methods,
            "channels": self.channels,
            "effective_channel": self.effective_channel,
            "failure_reasons": self.failure_reasons,
            "failure_classes": self.failure_classes,
            "recovery_hours_ist": self.recovery_hours_ist,
            "sufficiency": self.sufficiency,
            "sufficiency_reason": self.sufficiency_reason,
        }


@dataclass(frozen=True)
class Advisory:
    """One personalized recommendation. Advisory by construction."""

    payment_id: str
    contact_hash: str
    evidence: list
    recommended_channel: Optional[str]
    policy_ladder_next: Optional[str]
    overridden_by_policy: bool
    confidence: float
    rationale: str
    timing: dict
    sufficiency: str
    sufficiency_reason: str
    profile: dict = field(default_factory=dict)

    @property
    def advisory(self) -> bool:
        return True

    def to_dict(self) -> dict:
        return {
            "payment_id": self.payment_id,
            "contact_hash": self.contact_hash,
            "evidence": self.evidence,
            "recommended_channel": self.recommended_channel,
            "policy_ladder_next": self.policy_ladder_next,
            "overridden_by_policy": self.overridden_by_policy,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "timing": self.timing,
            "sufficiency": self.sufficiency,
            "sufficiency_reason": self.sufficiency_reason,
            "profile": self.profile,
            "advisory": True,
            "notice": ADVISORY_BANNER,
        }


# --- Gathering --------------------------------------------------------------


def prior_records(db: Session, record: PaymentFailureRecord) -> list:
    """
    Every other payment this system holds from the same contact.

    Matched on the normalized number rather than the stored string: Indian
    numbers arrive as +919876543210, 919876543210, 09876543210 and
    9876543210, and a profile that treated those as four customers would split
    one history into four and then report all four as having no history.

    The record being advised on is excluded. Including it would make an attempt
    already made on this payment count as proof that the channel works on this
    customer - circular, and flattering in exactly the wrong direction.
    """
    digits = normalize_phone(record.customer_phone)
    if not digits:
        return []

    # Two columns, then normalize, then load. A SQL LIKE would have to match the
    # raw stored string, and the raw strings are exactly what differ:
    # "+91 98123-45678" and "9812345678" are one customer and share no suffix.
    # Filtering in SQL would therefore drop the very records this function
    # exists to find, and no amount of normalizing afterwards can recover a row
    # the query already excluded.
    identities = (
        db.query(PaymentFailureRecord.payment_id, PaymentFailureRecord.customer_phone)
        .filter(PaymentFailureRecord.payment_id != record.payment_id)
        .all()
    )
    matching = [pid for pid, phone in identities if normalize_phone(phone) == digits]
    if not matching:
        return []

    return (
        db.query(PaymentFailureRecord)
        .filter(PaymentFailureRecord.payment_id.in_(matching))
        .order_by(PaymentFailureRecord.created_at)
        .all()
    )


def _recovery_hours(db: Session, records) -> list:
    """The IST hour each past recovery settled at, from the chain."""
    if not records:
        return []

    ids = [r.payment_id for r in records if r.recovery_state == "RECOVERED"]
    if not ids:
        return []

    rows = (
        db.query(AuditTrailEntry.timestamp_us)
        .filter(AuditTrailEntry.payment_id.in_(ids),
                AuditTrailEntry.action.like("STATE_%_TO_RECOVERED"))
        .order_by(AuditTrailEntry.sequence_no)
        .all()
    )
    return [
        datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc).astimezone(IST).hour
        for (us,) in rows
    ]


def build_profile(db: Session, record: PaymentFailureRecord) -> CustomerProfile:
    """Everything this system has seen from this contact, counted."""
    history = prior_records(db, record)
    recovered = [r for r in history if r.recovery_state == "RECOVERED"]
    failed = [r for r in history if r.recovery_state == "FAILED_STOPPED"]

    # The same attribution the dashboard uses, pointed at one customer.
    economics = by_intervention(db, history)["interventions"] if history else {}
    channels = {
        name: {"attempts": row["attempts"], "recovered": row["recovered"]}
        for name, row in economics.items()
    }

    # An effective channel requires a recovery, not merely an attempt. Three
    # ignored WhatsApp links say something about us, not about them.
    winners = [(row["recovered"], row["attempts"], name)
               for name, row in channels.items() if row["recovered"] > 0]
    effective = max(winners)[2] if winners else None

    resolved = len(recovered)
    if resolved < MIN_RESOLVED_FOR_ADVICE or effective is None:
        sufficiency = Sufficiency.NONE
        if not history:
            reason = ("No prior payments from this contact, so there is nothing "
                      "to personalize on.")
        elif not recovered:
            reason = (f"{_plural(len(history), 'prior payment')} from this "
                      f"contact, none recovered. Nothing here shows which "
                      f"channel works on them.")
        else:
            reason = (f"{_plural(resolved, 'resolved prior payment')}, but no "
                      f"recovery is attributable to a channel.")
    elif resolved < MIN_RESOLVED_FOR_PREFERENCE:
        sufficiency = Sufficiency.THIN
        reason = (f"{resolved} resolved prior payment. That is a data point, "
                  f"not yet a pattern.")
    else:
        sufficiency = Sufficiency.SUFFICIENT
        reason = f"{resolved} resolved prior payments from this contact."

    return CustomerProfile(
        contact_hash=contact_hash(record.customer_phone),
        payments_seen=len(history),
        recovered=resolved,
        failed=len(failed),
        open_count=len(history) - resolved - len(failed),
        methods=dict(Counter(r.method for r in history if r.method)),
        recovered_methods=dict(Counter(r.method for r in recovered if r.method)),
        channels=channels,
        effective_channel=effective,
        failure_reasons=dict(Counter(r.error_reason for r in history if r.error_reason)),
        failure_classes=dict(Counter(r.failure_class for r in history if r.failure_class)),
        recovery_hours_ist=_recovery_hours(db, history),
        sufficiency=sufficiency,
        sufficiency_reason=reason,
    )


# --- Advising ---------------------------------------------------------------


def _plural(n: int, singular: str, plural: Optional[str] = None) -> str:
    """`3 attempts` / `1 attempt`. Evidence a reader has to squint at is worse
    evidence, and "(s)" in a line a judge reads is squinting."""
    word = singular if n == 1 else (plural or f"{singular}s")
    return f"{n} {word}"


def _evidence(profile: CustomerProfile) -> list:
    """
    Plain statements, each carrying the count it came from.

    Evidence is only evidence if a reviewer can recompute it, so every line
    names its numbers. When there is nothing, it says nothing rather than
    padding the list to look substantial.
    """
    if profile.payments_seen == 0:
        return [NO_HISTORY_EVIDENCE]

    lines = [
        f"{_plural(profile.payments_seen, 'previous payment')} from this "
        f"contact: {profile.recovered} recovered, {profile.failed} stopped, "
        f"{profile.open_count} still open."
    ]

    for name, row in sorted(profile.channels.items(),
                            key=lambda kv: (-kv[1]["recovered"], kv[0])):
        lines.append(
            f"{name}: {_plural(row['attempts'], 'attempt')}, "
            f"{_plural(row['recovered'], 'recovery', 'recoveries')}."
        )

    if profile.recovered_methods:
        methods = ", ".join(f"{m} ({n})" for m, n in
                            sorted(profile.recovered_methods.items()))
        lines.append(f"Previously paid by {methods} after a recovery attempt.")

    repeats = [(reason, n) for reason, n in profile.failure_reasons.items() if n > 1]
    for reason, n in sorted(repeats, key=lambda kv: -kv[1]):
        lines.append(f"Repeated failure reason: {reason} ({n} of "
                     f"{profile.payments_seen}).")

    if len(profile.recovery_hours_ist) >= MIN_RECOVERIES_FOR_TIMING:
        hours = ", ".join(f"{h:02d}:00" for h in sorted(set(profile.recovery_hours_ist)))
        lines.append(f"Past recoveries settled around {hours} IST "
                     f"({len(profile.recovery_hours_ist)} observations).")

    return lines


def _ladder_next(db: Session, record: PaymentFailureRecord) -> Optional[str]:
    """
    Which rung the deterministic ladder would use next.

    Read straight off ATTEMPT_LADDER and the attempts already on the chain, so
    the advisory reports policy's intention rather than guessing at it. This is
    informational only - policy is still consulted for real, by the executor.
    """
    rungs = ATTEMPT_LADDER.get(record.failure_class, [])
    if not rungs:
        return None

    attempts = (
        db.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == record.payment_id,
                AuditTrailEntry.action.in_(ATTEMPT_ACTIONS))
    )
    if record.batch_id:
        attempts = attempts.filter(AuditTrailEntry.batch_id == record.batch_id)
    made = attempts.count()

    return rungs[made] if made < len(rungs) else None


def _confidence(profile: CustomerProfile) -> float:
    if profile.sufficiency == Sufficiency.NONE:
        return 0.0
    return round(min(CONFIDENCE_BASE + CONFIDENCE_PER_RESOLVED * profile.recovered,
                     CONFIDENCE_CAP), 2)


def _timing(
    db: Session,
    record: PaymentFailureRecord,
    profile: CustomerProfile,
    channel: Optional[str],
    now: datetime,
) -> dict:
    """
    Why now - or why not yet.

    Every branch is a constraint this system already enforces somewhere else,
    restated where a reader can see it. The customer's own historical hour is
    deliberately the weakest of them: it is reported as an observation and
    never used to hold a payment back, because two settlements is not a
    schedule.
    """
    def held(not_before: datetime, why: str) -> dict:
        return {"act_now": False, "not_before": not_before.isoformat(), "why": why}

    promised = record.promise_to_pay_at
    if promised is not None:
        if promised.tzinfo is None:
            promised = promised.replace(tzinfo=timezone.utc)
        if promised > now:
            return held(promised,
                        f"The customer stated they will pay by "
                        f"{promised.date().isoformat()}. Contacting them before "
                        f"that is the fastest way to be marked as spam.")

    if channel in VOICE_CHANNELS and in_quiet_hours(now):
        resume = next_permitted_time(now)
        return held(resume,
                    f"Inside TRAI quiet hours, and the recommended channel "
                    f"reaches the customer by voice. Permitted again from "
                    f"{resume.strftime('%H:%M')} IST.")

    last = (
        db.query(AuditTrailEntry.timestamp_us)
        .filter(AuditTrailEntry.payment_id == record.payment_id,
                AuditTrailEntry.action.in_(ATTEMPT_ACTIONS))
        .order_by(AuditTrailEntry.sequence_no.desc())
        .first()
    )
    if last is not None:
        touched = datetime.fromtimestamp(last[0] / 1_000_000, tz=timezone.utc)
        if now - touched < timedelta(minutes=FOLLOW_UP_AFTER_MINUTES):
            resume = touched + timedelta(minutes=FOLLOW_UP_AFTER_MINUTES)
            waited = int((now - touched).total_seconds() // 60)
            return held(resume,
                        f"Last contacted {_plural(waited, 'minute')} ago, inside the "
                        f"{FOLLOW_UP_AFTER_MINUTES}-minute follow-up window. "
                        f"A second message now reads as pressure.")

    hours = profile.recovery_hours_ist
    if len(hours) >= MIN_RECOVERIES_FOR_TIMING:
        common = Counter(hours).most_common(1)[0][0]
        return {
            "act_now": True,
            "not_before": None,
            "why": (f"No constraint blocks an attempt now. This contact's past "
                    f"recoveries settled around {common:02d}:00 IST "
                    f"({len(hours)} observations), which is a preference worth "
                    f"noting, not a reason to wait."),
        }

    return {
        "act_now": True,
        "not_before": None,
        "why": "No consent, quiet-hours, promise-to-pay or follow-up-window "
               "constraint applies to this record right now.",
    }


def advise(
    db: Session,
    record: PaymentFailureRecord,
    now: Optional[datetime] = None,
) -> Advisory:
    """
    One personalized recommendation for one record. Pure: reads only.

    The recommended channel is the one that has actually recovered money from
    this contact, when the history supports saying so, and the ladder's next
    rung otherwise. It is never anything else: the value is always a rung that
    already exists in policy.ATTEMPT_LADDER, so this cannot name a channel the
    system has no way to perform, cost or cap.
    """
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    profile = build_profile(db, record)
    ladder_next = _ladder_next(db, record)

    # The LADDER_RUNGS check is defence in depth and is expected to be
    # unreachable today: by_intervention only ever names rungs. It stays
    # because "the recommendation cannot name a channel the system has no way
    # to perform, cost or cap" should be true by construction here, not merely
    # true because of what another module currently happens to emit.
    # tests/test_customer_profile.py exercises it through that seam.
    personalized = (
        profile.effective_channel
        if profile.sufficiency != Sufficiency.NONE
        and profile.effective_channel in LADDER_RUNGS
        else None
    )
    channel = personalized or ladder_next
    overridden = bool(personalized and ladder_next and personalized != ladder_next)

    if personalized is None:
        rationale = (
            f"{profile.sufficiency_reason} Falling back to the deterministic "
            f"escalation ladder, which opens with "
            f"{ladder_next or 'no automated action'} for "
            f"{record.failure_class or 'an unclassified record'}."
        )
    elif overridden:
        rationale = (
            f"{personalized} has recovered "
            f"{profile.channels[personalized]['recovered']} of "
            f"{_plural(profile.channels[personalized]['attempts'], 'attempt')} "
            f"from this contact, which is the strongest signal in their "
            f"history. The "
            f"ladder for {record.failure_class} will use {ladder_next} instead, "
            f"and policy decides - this is a recommendation to weigh, not a "
            f"channel booked."
        )
    else:
        rationale = (
            f"{personalized} has recovered "
            f"{profile.channels[personalized]['recovered']} of "
            f"{_plural(profile.channels[personalized]['attempts'], 'attempt')} "
            f"from this contact, and it is also the ladder's next rung for "
            f"{record.failure_class}. History and policy agree here."
        )

    return Advisory(
        payment_id=record.payment_id,
        contact_hash=profile.contact_hash,
        evidence=_evidence(profile),
        recommended_channel=channel,
        policy_ladder_next=ladder_next,
        overridden_by_policy=overridden,
        confidence=_confidence(profile),
        rationale=rationale,
        timing=_timing(db, record, profile, channel, moment),
        sufficiency=profile.sufficiency,
        sufficiency_reason=profile.sufficiency_reason,
        profile=profile.to_dict(),
    )


# --- Persistence ------------------------------------------------------------


def _headline(advisory: Advisory) -> str:
    channel = advisory.recommended_channel or "no automated action"
    override = (f" The ladder will use {advisory.policy_ladder_next} instead."
                if advisory.overridden_by_policy else "")
    return (
        f"{ADVISORY_BANNER}. Customer history points to {channel} at "
        f"{advisory.confidence:.0%} confidence "
        f"(evidence: {advisory.sufficiency}).{override} Recorded, not executed."
    )


def record_advisory(
    db: Session,
    record: PaymentFailureRecord,
    advisory: Advisory,
) -> AuditTrailEntry:
    """
    Append the recommendation to the existing ledger. Zero cost, no transition.

    Stored the same way ai_advisor stores its own: a sentence a person can read
    in the audit trail, then the structured body behind a marker. Serialized
    with sorted keys and no whitespace so the same advisory produces the same
    bytes, and therefore the same entry hash, on any machine.
    """
    body = json.dumps(advisory.to_dict(), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)

    return log_audit(
        db, record,
        action=ADVISORY_ACTION,
        actor=ADVISORY_ACTOR,
        details=f"{_headline(advisory)}\n{ADVISORY_MARKER}{body}",
        cost_paise=0,
        llm_metadata=None,
    )


# Both advisories are stored the same way, behind the same marker, so they are
# read back by the same function. This was a byte-identical copy until the
# cleanup pass; two copies of a parser is two places for a storage-format change
# to be applied to only one of them.
parse = ai_advisor.parse


def latest_for(db: Session, payment_id: str) -> Optional[dict]:
    """The most recently recorded advisory for this record, or None."""
    entry = (
        db.query(AuditTrailEntry)
        .filter(AuditTrailEntry.payment_id == payment_id,
                AuditTrailEntry.action == ADVISORY_ACTION)
        .order_by(AuditTrailEntry.sequence_no.desc())
        .first()
    )
    return None if entry is None else parse(entry.details)


def insight_for(
    db: Session,
    record: PaymentFailureRecord,
    now: Optional[datetime] = None,
) -> dict:
    """
    What the APIs serve.

    Computed on read rather than replayed from the ledger, so a record whose
    history has grown since the advisory was written shows the current reading
    - which is the whole point of feeding outcomes back. The recorded entry
    remains the evidence of what was advised at the time.
    """
    return advise(db, record, now=now).to_dict()
