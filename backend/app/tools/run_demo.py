"""
Run the seeded demo batch and print a receipt.

    python -m app.tools.run_demo

Deterministic: the same seed produces the same numbers - including the same
ledger head hash - on every run and on every machine. The figures quoted in
the README come from this command, so a reviewer can compare them line by line.

Why this writes to its own database
-----------------------------------
The ledger is append-only and the attempt counter is scoped to a batch, so
re-running into an existing database would let the previous run's attempts
count against the new one and trip the caps immediately. The receipt therefore
builds a throwaway `recoveros_demo.db` from scratch each time. The API's own
database is never touched.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import os
import sys
from pathlib import Path

# Must be set before app.database is imported, since the engine is built at
# import time from DATABASE_URL.
DEMO_DB = Path(__file__).resolve().parents[2] / "recoveros_demo.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DEMO_DB.as_posix()}"

import asyncio  # noqa: E402

from app import ledger, __about__  # noqa: E402
from app.config import (  # noqa: E402
    CAC_CEILING_PERCENT,
    HOLDOUT_PERCENT,
    MAX_RETRIES,
    MERCHANT_MARGIN_PERCENT,
    RECOVEROS_SEED,
)
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models import install_append_only_triggers  # noqa: E402
import app.recovery_simulator as simulator  # noqa: E402

# Stopping rules first, bookkeeping second.
REASON_ORDER = [
    "RETRY_CAP_REACHED",
    "CAC_CEILING",
    "NEGATIVE_EXPECTED_VALUE",
    "CONSENT_WITHDRAWN",
    "QUIET_HOURS_DEFERRED",
    "HARD_DECLINE",
    "ESCALATED_TO_HUMAN",
    "LADDER_EXHAUSTED",
    "HOLDOUT_CONTROL",
]

RULE = "=" * 72
THIN = "-" * 72


def rupees(paise: int) -> str:
    return f"Rs {paise / 100:,.2f}"


# 2026-08-25T00:00:00Z, in microseconds. Fixed so the demo's ledger hashes are
# byte-identical between runs and between machines.
DEMO_EPOCH_US = 1_787_616_000_000_000
DEMO_TICK_US = 1_000  # 1ms between entries, enough to keep order legible


def install_virtual_clock() -> None:
    """
    Give the demo a deterministic clock.

    Wall-clock timestamps are part of the hash preimage, so a real ledger
    produces a different head hash on every run - correct for production,
    useless for a reproducibility claim. The API never installs this.
    """
    state = {"t": DEMO_EPOCH_US}

    def tick() -> int:
        state["t"] += DEMO_TICK_US
        return state["t"]

    ledger.set_clock(tick)


def reset_database() -> None:
    """Drop the throwaway demo database so every run starts from genesis."""
    engine.dispose()
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(DEMO_DB) + suffix)
        if candidate.exists():
            candidate.unlink()
    Base.metadata.create_all(bind=engine)
    install_append_only_triggers(engine)


async def run() -> tuple[dict, ledger.VerificationResult]:
    original_sleep = simulator.asyncio.sleep

    async def no_sleep(_delay):
        return None

    # The stagger exists for the live dashboard; a receipt should not take
    # twenty seconds to print.
    simulator.asyncio.sleep = no_sleep
    db = SessionLocal()
    try:
        from app.routes.llm import build_activity

        result = await simulator.run_batch_simulation(db, f"demo_{RECOVEROS_SEED}")
        return result, ledger.verify_chain(db), build_activity(db)
    finally:
        simulator.asyncio.sleep = original_sleep
        db.close()


def main() -> int:
    reset_database()
    install_virtual_clock()
    result, verification, activity = asyncio.run(run())

    treated = result["treated_count"]
    control = result["control_count"]
    control_recovered = result["control_recovered"]
    treated_recovered = result["recovered_count"] - control_recovered

    treated_rate = treated_recovered / treated * 100 if treated else 0.0
    control_rate = control_recovered / control * 100 if control else 0.0

    print(RULE)
    print("  RecoverOS - Demo Batch Receipt")
    print(f"  {__about__.banner()}")
    print(RULE)
    print(f"  Seed                : {result['seed']}  (deterministic)")
    print(f"  Records             : {result['total_records']}")
    print(f"  Attempt cap         : {MAX_RETRIES} per payment")
    print(f"  Cost ceiling        : {CAC_CEILING_PERCENT}% of payment value")
    print(f"  Assumed margin      : {MERCHANT_MARGIN_PERCENT}%")
    print(f"  Holdout             : {HOLDOUT_PERCENT}% of contacts, never contacted")
    print(THIN)
    print("  OUTCOME")
    print(f"    treated           : {treated:>3} records, {treated_recovered:>3} recovered  ({treated_rate:.1f}%)")
    print(f"    control           : {control:>3} records, {control_recovered:>3} recovered  ({control_rate:.1f}%)")
    print(f"    attributable      : {result['attributable_count']:>3} payments worth {rupees(result['attributable_gmv'])}")
    print(f"    channel spend     : {rupees(result['channel_cost_paise'])}")
    print()
    print(f"    Lift is deliberately NOT quoted here: n={control} controls cannot")
    print("    support a causal estimate. See results/lift_analysis.md, which")
    print("    measures 2,000 contacts across 10 seeds and reports a 95% CI.")
    print(THIN)
    print("  WHY WE STOPPED")
    codes = result["reason_codes"]
    for code in REASON_ORDER:
        if code in codes:
            print(f"    {codes[code]:>3}  {code}")
    for code, count in sorted(codes.items()):
        if code not in REASON_ORDER:
            print(f"    {count:>3}  {code}")
    print(THIN)
    print("  AI ACTIVITY")
    split = activity["classification_split"]
    print(f"    model calls       : {activity['total_calls']}")
    print(f"    classified by     : {split['rule_engine']} rule engine / "
          f"{split['llm_agent']} llm agent")
    print(f"    tokens in / out   : {activity['total_input_tokens']} / "
          f"{activity['total_output_tokens']}")
    print(f"    mean latency      : {activity['mean_latency_ms']} ms")
    print(f"    copy rejected     : {activity['rejections']}")
    for action, count in sorted(activity["by_action"].items()):
        print(f"      {count:>3}  {action}")
    print()
    print("    Responses are replayed from backend/data/llm_cache.json, recorded")
    print("    against live Gemini. That is what lets this run reproduce exactly.")
    print(THIN)
    print("  LEDGER")
    print(f"    entries           : {verification.entries_checked}")
    status = "VALID" if verification.valid else f"BROKEN - {verification.reason}"
    print(f"    chain             : {status}")
    print(f"    head              : {verification.head_hash}")
    print(RULE)
    print("  Run this again - every number above, head hash included, repeats.")
    print("  Verify the chain     : python -m app.tools.verify_ledger")
    print("  Break it on purpose  : python -m app.tools.tamper_demo")
    print(THIN)
    print(f"  {__about__.NOTICE}")
    print(f"  {__about__.PROJECT_URL}")
    print(RULE)

    return 0 if verification.valid else 1


if __name__ == "__main__":
    sys.exit(main())
