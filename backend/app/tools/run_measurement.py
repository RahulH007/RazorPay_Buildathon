"""
Measure incremental lift over a population large enough to support the claim.

    python -m app.tools.run_measurement [--contacts 2000] [--seeds 10]

Why this is separate from the demo batch
----------------------------------------
The demo batch holds ~57 records, so a 20% holdout is about 12 controls. At
that size the control recovery rate swings between 0% and 42% purely by which
contacts land in the arm - we measured exactly that spread across ten seeds.
A lift number computed from twelve observations is not evidence, and this
project's whole claim is that we do not overstate.

So the demo batch shows the mechanism, and this shows the number. Runs
headless with no database: the policy ladder and the outcome engine are pure
functions of the record, which is what makes them measurable this way.
"""

import argparse
import hashlib
import statistics
import sys
from pathlib import Path

from app.config import (
    CHANNEL_COSTS_PAISE,
    HOLDOUT_PERCENT,
    MAX_RETRIES,
    MERCHANT_MARGIN_PERCENT,
    RECOVEROS_SEED,
)
from app.outcome_engine import (
    Behaviour,
    OBSERVATION_WINDOW_HOURS,
    attempt_outcome,
    control_outcome,
    draw,
)
from app.policy import ATTEMPT_LADDER, CHANNEL_ACTION_COST_PAISE
from app.tools.seed_behavior import PRIORS

# Class mix and typical ticket sizes, matched to the demo dataset so the
# larger population is the same shape rather than a different problem.
CLASS_MIX = {
    "TRANSIENT_TECHNICAL": (0.26, 45000, 800000),
    "AUTH_FRICTION": (0.23, 30000, 600000),
    "MANDATE_BALANCE": (0.28, 50000, 400000),
    "B2B_RECEIVABLE": (0.16, 200000, 5000000),
    "HARD_DECLINE": (0.07, 20000, 300000),
}


def synth_population(n: int, seed: int) -> list:
    """Build a population from the same priors that generated the demo data."""
    population = []
    thresholds, cumulative = [], 0.0
    for failure_class, (share, low, high) in CLASS_MIX.items():
        cumulative += share
        thresholds.append((cumulative, failure_class, low, high))

    for i in range(n):
        pid = f"synth_{seed}_{i:06d}"
        pick = draw(pid, seed, "class")
        failure_class, low, high = next(
            (c, lo, hi) for t, c, lo, hi in thresholds if pick <= t
        )

        amount = int(low + (high - low) * draw(pid, seed, "amount"))
        prior = PRIORS[failure_class]

        natural = None
        if draw(pid, seed, "natural") < prior["natural_rate"]:
            lo_h, hi_h = prior["natural_window"]
            natural = round(lo_h + (hi_h - lo_h) * draw(pid, seed, "natural_when"), 1)

        population.append({
            "payment_id": pid,
            "failure_class": failure_class,
            "amount": amount,
            "behaviour": Behaviour(
                natural_recovery_hours=natural,
                responds_to=dict(prior["responds_to"]),
            ),
        })
    return population


def is_holdout(payment_id: str, seed: int, percent: int) -> bool:
    """
    Deterministic arm assignment.

    One synthetic contact holds exactly one payment here, so hashing the id is
    equivalent to hashing the contact - the contact-level property that matters
    in the real batch is preserved rather than sidestepped.
    """
    digest = hashlib.sha256(f"holdout|{payment_id}|{seed}".encode()).digest()
    return int.from_bytes(digest[:4], "big") % 100 < percent


def run_treated(record: dict, seed: int) -> tuple[bool, bool, int]:
    """Walk the ladder. Returns (recovered, attributable, spend_paise)."""
    ladder = ATTEMPT_LADDER.get(record["failure_class"], [])
    ceiling = record["amount"] * 15 // 100
    rate = {
        "TRANSIENT_TECHNICAL": 0.85, "AUTH_FRICTION": 0.40,
        "MANDATE_BALANCE": 0.55, "B2B_RECEIVABLE": 0.50, "HARD_DECLINE": 0.0,
    }[record["failure_class"]]
    expected = int(record["amount"] * rate * MERCHANT_MARGIN_PERCENT / 100)

    spend = 0
    for attempt, channel in enumerate(ladder):
        if attempt >= MAX_RETRIES:
            break
        cost = CHANNEL_ACTION_COST_PAISE.get(channel, 0)
        if spend + cost > ceiling:
            break
        if cost > 0 and cost > expected:
            break

        spend += cost
        outcome = attempt_outcome(
            record["payment_id"], record["behaviour"], channel, attempt, seed
        )
        if outcome.recovered:
            return True, outcome.attributable, spend

    return False, False, spend


def run_once(population: list, seed: int) -> dict:
    treated = control = 0
    treated_recovered = control_recovered = 0
    treated_gmv = control_gmv = attributable_gmv = 0
    spend_paise = 0

    for record in population:
        if is_holdout(record["payment_id"], seed, HOLDOUT_PERCENT):
            control += 1
            if control_outcome(record["behaviour"]).recovered:
                control_recovered += 1
                control_gmv += record["amount"]
        else:
            treated += 1
            recovered, attributable, spend = run_treated(record, seed)
            spend_paise += spend
            if recovered:
                treated_recovered += 1
                treated_gmv += record["amount"]
                if attributable:
                    attributable_gmv += record["amount"]

    treated_rate = treated_recovered / treated * 100 if treated else 0
    control_rate = control_recovered / control * 100 if control else 0

    return {
        "treated": treated,
        "control": control,
        "treated_rate": treated_rate,
        "control_rate": control_rate,
        "lift_pp": treated_rate - control_rate,
        "treated_gmv": treated_gmv,
        "attributable_gmv": attributable_gmv,
        "spend_paise": spend_paise,
        # Incremental GMV: what the treated arm recovered above the rate the
        # untreated arm reached on its own.
        "incremental_gmv": int(treated_gmv - (control_rate / 100) * treated
                               * (treated_gmv / treated_recovered if treated_recovered else 0)),
    }


def ci95(values: list) -> tuple[float, float]:
    """Normal-approximation 95% interval on the mean across seeds."""
    if len(values) < 2:
        return (values[0], values[0]) if values else (0.0, 0.0)
    mean = statistics.mean(values)
    margin = 1.96 * statistics.stdev(values) / (len(values) ** 0.5)
    return mean - margin, mean + margin


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contacts", type=int, default=2000)
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    runs = []
    for offset in range(args.seeds):
        seed = RECOVEROS_SEED + offset
        runs.append(run_once(synth_population(args.contacts, seed), seed))

    lifts = [r["lift_pp"] for r in runs]
    treated_rates = [r["treated_rate"] for r in runs]
    control_rates = [r["control_rate"] for r in runs]

    lift_lo, lift_hi = ci95(lifts)
    total_spend = sum(r["spend_paise"] for r in runs) / len(runs)
    incremental = sum(r["incremental_gmv"] for r in runs) / len(runs)
    margin_value = incremental * MERCHANT_MARGIN_PERCENT / 100

    lines = []
    add = lines.append
    add("# RecoverOS - Incremental Lift Measurement")
    add("")
    add(f"- Population per run: **{args.contacts:,} contacts**")
    add(f"- Runs: **{args.seeds}** (seeds {RECOVEROS_SEED}-{RECOVEROS_SEED + args.seeds - 1})")
    add(f"- Holdout: **{HOLDOUT_PERCENT}%**, never contacted")
    add(f"- Observation window: **{OBSERVATION_WINDOW_HOURS}h**")
    add(f"- Assumed merchant margin: **{MERCHANT_MARGIN_PERCENT}%**")
    add("")
    add("## Result")
    add("")
    add("| Metric | Value |")
    add("|---|---|")
    add(f"| Treated recovery rate | {statistics.mean(treated_rates):.1f}% |")
    add(f"| Control recovery rate (uncontacted) | {statistics.mean(control_rates):.1f}% |")
    add(f"| **Incremental lift** | **{statistics.mean(lifts):+.1f} pp** "
        f"(95% CI {lift_lo:+.1f} to {lift_hi:+.1f}) |")
    add(f"| Incremental GMV per run | Rs {incremental / 100:,.0f} |")
    add(f"| Value at {MERCHANT_MARGIN_PERCENT}% margin | Rs {margin_value / 100:,.0f} |")
    add(f"| Channel spend per run | Rs {total_spend / 100:,.2f} |")
    incremental_recoveries = statistics.mean(
        [r["lift_pp"] / 100 * r["treated"] for r in runs]
    )
    add(f"| Incremental recoveries per run | {incremental_recoveries:,.0f} payments |")
    add(f"| **Cost per incremental recovery** | **Rs {total_spend / incremental_recoveries / 100:,.2f}** |")
    add("")
    add("## Why the control rate is not zero")
    add("")
    add("A meaningful share of failed payments recover with no intervention at")
    add("all - transient bank faults especially. The control arm measures that,")
    add("and only the difference is claimed. Reporting the treated rate alone")
    add(f"would overstate this system's contribution by "
        f"{statistics.mean(control_rates):.1f} percentage points.")
    add("")
    add("## What actually constrains this")
    add("")
    add("Channel spend is small because messaging in India is cheap - well under")
    add("a rupee to reach a customer holding a payment worth thousands. The")
    add("binding constraint on recovery is therefore not budget but consent and")
    add("customer tolerance, which is why the stopping rules matter more than")
    add("the cost ceiling for most records. The CAC ceiling only bites on")
    add("micro-payments, where it correctly refuses to spend 50p chasing 40p.")
    add("")
    add("## Per-run detail")
    add("")
    add("| Seed | Treated | Control | Lift (pp) |")
    add("|---|---|---|---|")
    for offset, run in enumerate(runs):
        add(f"| {RECOVEROS_SEED + offset} | {run['treated_rate']:.1f}% | "
            f"{run['control_rate']:.1f}% | {run['lift_pp']:+.1f} |")
    report = "\n".join(lines) + "\n"

    print(report)
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        print(f"[written] {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
