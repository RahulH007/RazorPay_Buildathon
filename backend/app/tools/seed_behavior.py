"""
Attach a stated counterfactual to every record in the demo dataset.

The behaviour block is written into the dataset file rather than computed at
runtime, so a reviewer can open the JSON and read exactly what each customer
would have done without us. A counterfactual hidden inside code is not
evidence; one sitting in the input data is.

Run once:  python -m app.tools.seed_behavior
"""

import json
import sys
from pathlib import Path

from app.classifier import RULE_MAP
from app.outcome_engine import draw

DATASET = Path(__file__).parent.parent.parent / "data" / "test_batch_50.json"
SEED = 20260825

# Priors per failure class, chosen to reflect how these failures actually
# behave rather than to flatter the system.
#
# `natural_rate` is the share who pay unprompted. It is deliberately HIGH for
# transient bank faults: the bank comes back and the customer retries, so most
# of that revenue arrives with or without us. A system that claimed credit for
# it would be overstating its value by a wide margin - and this dataset is
# built so the measurement catches that.
PRIORS = {
    "TRANSIENT_TECHNICAL": {
        "natural_rate": 0.60,
        "natural_window": (1.0, 20.0),
        # 0.45 per attempt over 3 attempts compounds to ~83%, which is
        # about right for a bank fault that mostly clears on its own.
        "responds_to": {"silent_retry": 0.45},
    },
    "AUTH_FRICTION": {
        "natural_rate": 0.25,
        "natural_window": (2.0, 48.0),
        # ~30% per message, compounding to ~51% over two sends, is in
        # line with published WhatsApp payment-recovery rates.
        "responds_to": {"whatsapp_link": 0.30},
    },
    "MANDATE_BALANCE": {
        "natural_rate": 0.15,
        "natural_window": (12.0, 60.0),
        "responds_to": {"upi_resequence": 0.35, "whatsapp_link": 0.25},
    },
    "B2B_RECEIVABLE": {
        "natural_rate": 0.20,
        "natural_window": (24.0, 70.0),
        "responds_to": {"whatsapp_link": 0.25, "hinglish_voice": 0.40,
                        "human_queue": 0.35},
    },
    "HARD_DECLINE": {
        "natural_rate": 0.0,
        "natural_window": (0.0, 0.0),
        "responds_to": {},
    },
}


def build_behaviour(payment_id: str, failure_class: str) -> dict:
    prior = PRIORS[failure_class]

    natural_hours = None
    if draw(payment_id, SEED, "natural") < prior["natural_rate"]:
        low, high = prior["natural_window"]
        spread = draw(payment_id, SEED, "natural_when")
        natural_hours = round(low + (high - low) * spread, 1)

    return {
        "natural_recovery_at_hours": natural_hours,
        "responds_to": dict(prior["responds_to"]),
    }


def main() -> int:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))

    counts = {}
    for record in dataset:
        failure_class = RULE_MAP[record["error"]["reason"]].value
        record["behavior"] = build_behaviour(record["payment_id"], failure_class)
        bucket = counts.setdefault(failure_class, {"n": 0, "natural": 0})
        bucket["n"] += 1
        if record["behavior"]["natural_recovery_at_hours"] is not None:
            bucket["natural"] += 1

    DATASET.write_text(
        json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Behaviour written for {len(dataset)} records (seed {SEED}).")
    print()
    print(f"  {'class':<22} {'n':>4} {'would pay unprompted':>22}")
    print("  " + "-" * 50)
    for failure_class, bucket in sorted(counts.items()):
        share = bucket["natural"] / bucket["n"] * 100 if bucket["n"] else 0
        print(f"  {failure_class:<22} {bucket['n']:>4} "
              f"{bucket['natural']:>10} ({share:>4.0f}%)")
    print()
    print("  The transient share is high on purpose: most of that revenue")
    print("  arrives with or without us, and the holdout is what stops us")
    print("  taking credit for it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
