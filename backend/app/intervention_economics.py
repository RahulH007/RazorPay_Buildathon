"""
RecoverOS Intervention Economics
Which recovery action recovered how much money, at what cost, at what return.

The dashboard could already say how much came back. It could not say what
brought it back, which is the question a merchant asks second and the one that
decides where the next rupee of recovery budget goes. A 30% recovery rate is a
fact about the batch; "the voice call earns 250x and the WhatsApp link earns
400x, so send more links" is a fact someone can act on.

Nothing new is recorded to produce it. Every attempt has been a ledger entry
carrying its own cost in integer paise since the first batch ran, and every
recovery is a state transition on the same chain, so this module is a read.
There is no second tracking table to drift out of step with the first, and no
new column: an attribution that disagreed with the ledger would be worse than
no attribution at all.

The attribution rule is deliberately narrow:

    a recovery is credited to the last attempt made before the record
    transitioned to RECOVERED, and to nothing at all when no attempt
    preceded it

Both halves matter. Crediting the last attempt is what lets an escalation
ladder report honestly - when a WhatsApp link is ignored and the Hinglish voice
call that follows gets paid, the voice call is what closed it, and splitting
the credit or handing it to the first rung would make the cheap channel look
like it earned money the expensive one had to go and fetch.

Crediting nothing is what keeps the holdout arm honest. The control group is
never contacted and some of it pays anyway; those rupees are real, they are
counted, and they belong to no channel. A system that quietly handed them to
whichever intervention happened to be nearby would be reporting a return it
did not earn.

Scoping matches the cohort scoping in routes/metrics.py, batch id included.
The ledger is append-only, so re-running a batch adds entries against the same
payment ids; keying on payment id alone would sum every run ever performed and
make each channel look more expensive on every demo.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AuditTrailEntry
from app.state_machine import VALID_TRANSITIONS

# Ledger action -> the policy engine's own channel name.
#
# Both halves of every pair already exist. The keys are the actions
# recovery_actions writes and guardrails.ATTEMPT_ACTIONS counts against the
# retry cap; the values are the rung names in policy.ATTEMPT_LADDER. No new
# vocabulary is introduced here, because a channel that only this module knows
# about could never be chosen, costed or capped by anything else.
#
# ESCALATED_TO_HUMAN is included where the retry cap excludes it, and the
# difference is intentional: a handoff to the accounts team is not an automated
# attempt and must not consume a retry, but it is unquestionably an
# intervention, and a table that omitted it would silently drop every B2B
# invoice that reached the end of the ladder.
INTERVENTION_BY_ACTION = {
    "RETRY_SILENT_ATTEMPT": "silent_retry",
    "WHATSAPP_LINK_SENT": "whatsapp_link",
    "MANDATE_RESEQUENCED": "upi_resequence",
    "VOICE_CALL_INITIATED": "hinglish_voice",
    "ESCALATED_TO_HUMAN": "human_queue",
}

# The transitions that mean "this record was won", derived from the state
# machine rather than transcribed from it. A new state that may reach RECOVERED
# is picked up here without anyone remembering to; a hardcoded pair would leave
# its recoveries credited to whatever attempt happened to be last in the trail.
RECOVERY_TRANSITION_ACTIONS = frozenset(
    f"STATE_{state}_TO_RECOVERED"
    for state, allowed in VALID_TRANSITIONS.items()
    if "RECOVERED" in allowed
)

_TRACKED_ACTIONS = tuple(INTERVENTION_BY_ACTION) + tuple(RECOVERY_TRANSITION_ACTIONS)

# SQLite caps a statement at 999 bound parameters, and this binds one per
# payment id. routes/metrics.py holds the same cap for the same reason; the two
# walks of the ledger are deliberately independent, so that the per-channel
# costs agreeing with the headline cost is evidence rather than a tautology.
ID_CHUNK = 400


def _scoped_entries(db: Session, records) -> dict:
    """
    Every tracked ledger entry for these records, keyed by payment id and
    ordered by sequence number.

    Grouped by each record's own batch id, then filtered to it - the same rule
    routes/metrics.py uses for cost. That is what confines the reading to this
    episode of the record's life rather than its entire recorded past.
    """
    by_batch = defaultdict(list)
    for record in records:
        by_batch[record.batch_id].append(record.payment_id)

    trails = defaultdict(list)
    for batch_id, payment_ids in by_batch.items():
        for start in range(0, len(payment_ids), ID_CHUNK):
            chunk = payment_ids[start:start + ID_CHUNK]
            query = db.query(
                AuditTrailEntry.payment_id,
                AuditTrailEntry.sequence_no,
                AuditTrailEntry.action,
                AuditTrailEntry.cost_paise,
            ).filter(
                AuditTrailEntry.payment_id.in_(chunk),
                AuditTrailEntry.action.in_(_TRACKED_ACTIONS),
            )
            if batch_id is None:
                query = query.filter(AuditTrailEntry.batch_id.is_(None))
            else:
                query = query.filter(AuditTrailEntry.batch_id == batch_id)

            # A payment id is a primary key, so it belongs to exactly one batch
            # group and one chunk - which is what makes per-chunk ordering
            # sufficient to order each record's whole trail.
            for row in query.order_by(AuditTrailEntry.sequence_no).all():
                trails[row.payment_id].append(row)

    return trails


def _cohort_spend(db: Session, records) -> int:
    """
    Every paise the ledger charged against these records, whatever wrote it.

    Computed separately from the per-channel totals, and on purpose: comparing
    a sum over the five attributed actions against a sum over all entries is
    what turns "the table accounts for the spend" into a checkable claim. A
    cost written by something this module does not recognise shows up as a
    residual rather than disappearing.
    """
    by_batch = defaultdict(list)
    for record in records:
        by_batch[record.batch_id].append(record.payment_id)

    total = 0
    for batch_id, payment_ids in by_batch.items():
        for start in range(0, len(payment_ids), ID_CHUNK):
            chunk = payment_ids[start:start + ID_CHUNK]
            query = db.query(func.sum(AuditTrailEntry.cost_paise)).filter(
                AuditTrailEntry.payment_id.in_(chunk)
            )
            if batch_id is None:
                query = query.filter(AuditTrailEntry.batch_id.is_(None))
            else:
                query = query.filter(AuditTrailEntry.batch_id == batch_id)
            total += query.scalar() or 0

    return total


def _blank(channel: str) -> dict:
    return {
        "intervention": channel,
        "attempts": 0,
        "records": 0,
        "recovered": 0,
        "recovered_gmv_paise": 0,
        "cost_paise": 0,
    }


def _finalise(row: dict) -> dict:
    """Turn the running totals into the figures the dashboard reads."""
    records = row["records"]
    recovered = row["recovered"]
    cost = row["cost_paise"]
    gmv = row["recovered_gmv_paise"]
    net = gmv - cost

    row["recovery_rate"] = round(recovered / records * 100, 1) if records else 0.0
    row["net_recovery_paise"] = net
    # A free channel has no return on investment, only a return. Reporting an
    # infinite or a zero ROI for silent retry would sit a made-up number beside
    # real ones, so the field is null and the UI renders a dash.
    row["roi"] = round(net / cost, 2) if cost else None
    row["average_recovered_paise"] = gmv // recovered if recovered else 0

    # Rupee mirrors, rendered once here rather than in three places on screen.
    row["recovered_gmv"] = gmv / 100.0
    row["cost"] = cost / 100.0
    row["net_recovery"] = net / 100.0
    row["average_recovered"] = row["average_recovered_paise"] / 100.0
    return row


def by_intervention(db: Session, records) -> dict:
    """
    Recovery economics for one cohort, broken down by the action taken.

    `records` is the cohort the dashboard is already reporting on, passed in
    rather than re-queried so the table cannot describe a different population
    from the headline figures above it.

    Returns {"interventions": {channel: row, ...}, "summary": {...}}, with the
    channels ordered strongest first so the UI ranks them without re-sorting.
    """
    trails = _scoped_entries(db, records)

    buckets: dict[str, dict] = {}
    attributed_cost = 0
    unattributed_recovered = 0
    unattributed_gmv = 0

    for record in records:
        trail = trails.get(record.payment_id, ())

        touched = set()
        for row in trail:
            channel = INTERVENTION_BY_ACTION.get(row.action)
            if channel is None:
                continue
            bucket = buckets.setdefault(channel, _blank(channel))
            bucket["attempts"] += 1
            bucket["cost_paise"] += row.cost_paise or 0
            attributed_cost += row.cost_paise or 0
            touched.add(channel)

        for channel in touched:
            buckets[channel]["records"] += 1

        if record.recovery_state != "RECOVERED":
            continue

        # The cutoff is the recovery itself. An entry written afterwards cannot
        # have caused the settlement, and reading the last attempt overall would
        # hand it the money. When no transition is on the chain for this episode
        # the whole trail is in scope, which is the honest reading of a record
        # whose recovery predates the ledger it is being measured against.
        cutoff = next(
            (row.sequence_no for row in trail
             if row.action in RECOVERY_TRANSITION_ACTIONS),
            None,
        )
        preceding = [
            row for row in trail
            if row.action in INTERVENTION_BY_ACTION
            and (cutoff is None or row.sequence_no < cutoff)
        ]

        if not preceding:
            unattributed_recovered += 1
            unattributed_gmv += record.amount
            continue

        credited = buckets[INTERVENTION_BY_ACTION[preceding[-1].action]]
        credited["recovered"] += 1
        credited["recovered_gmv_paise"] += record.amount

    rows = [_finalise(row) for row in buckets.values()]

    # Strongest first, ties broken by name so the same database never renders
    # in two different orders. Net recovery rather than ROI: a channel that
    # spends 50p to win Rs 1,000 outranks one that spends nothing to win Rs 10,
    # and it is the rupees a merchant is deciding about.
    rows.sort(key=lambda row: (-row["net_recovery_paise"], row["intervention"]))

    # "Strongest" has to mean "won the most money", not "lost the least". In a
    # cohort where nothing recovered, every net is zero or negative and the
    # cheapest channel would otherwise win by default.
    winners = [row for row in rows if row["recovered"] > 0]

    cohort_cost = _cohort_spend(db, records)
    return {
        "interventions": {row["intervention"]: row for row in rows},
        "summary": {
            "strongest": winners[0]["intervention"] if winners else None,
            "ranked_by": "net_recovery_paise",
            "attributed_cost_paise": attributed_cost,
            # Reported beside the attributed figure rather than assumed equal.
            # Today every paise the ledger carries is written by one of the
            # five actions above, so these agree; if an action added later
            # starts costing money without appearing in the table, the
            # difference shows up here instead of quietly vanishing.
            "cohort_cost_paise": cohort_cost,
            "unattributed_cost_paise": cohort_cost - attributed_cost,
            "attributed_recovered": sum(row["recovered"] for row in rows),
            "unattributed_recovered": unattributed_recovered,
            "unattributed_recovered_gmv_paise": unattributed_gmv,
            "unattributed_recovered_gmv": unattributed_gmv / 100.0,
        },
    }
