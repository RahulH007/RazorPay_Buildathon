"""
Extend the demo dataset with records that deliberately trip each stopping rule.

A guardrail nobody can watch fire is indistinguishable from one that does not
work — which was the original defect. These records exist so every reason code
appears in a normal demo run, with the arithmetic chosen so each one fires for
the reason it claims.

Run once:  python -m app.tools.seed_guard_cases
"""

import json
import sys
from pathlib import Path

DATASET = Path(__file__).parent.parent.parent / "data" / "test_batch_50.json"

# Ceiling is 15% of the amount; expected value is amount x success-rate x 20%
# margin. Amounts below are picked so the intended rule is the first to fail.
#
#   AUTH_FRICTION  rate 0.40, WhatsApp 50p
#     Rs 6.50 (650p): EV 52p >= 50p so attempt 1 proceeds; attempt 2 would take
#                     spend to 100p against a 97p ceiling  -> CAC_CEILING
#     Rs 5.00 (500p): EV 40p < 50p on the very first attempt -> NEGATIVE_EV
#
#   B2B_RECEIVABLE rate 0.50, WhatsApp 50p then voice 200p
#     Rs 15.00 (1500p): WhatsApp fine; voice takes spend to 250p against a
#                       225p ceiling -> CAC_CEILING
GUARD_CASES = [
    {
        "payment_id": "pay_CAC01micro1",
        "amount": 650,
        "method": "upi",
        "customer": {"name": "Ramesh Yadav", "email": "ramesh.yadav@example.com",
                     "phone": "+919812340001"},
        "error": {"source": "customer", "step": "payment_authentication",
                  "reason": "authentication_failed",
                  "description": "UPI PIN entry timed out on a Rs 6.50 QR payment"},
        "_why": "CAC_CEILING on attempt 2 - recovery costs more than the payment is worth",
    },
    {
        "payment_id": "pay_NEV01micro2",
        "amount": 500,
        "method": "upi",
        "customer": {"name": "Sunita Devi", "email": None, "phone": "+919812340002"},
        "error": {"source": "customer", "step": "payment_authentication",
                  "reason": "incorrect_otp",
                  "description": "Wrong OTP on a Rs 5 chai QR payment"},
        "_why": "NEGATIVE_EXPECTED_VALUE on attempt 1 - a 50p message chasing 40p of margin",
    },
    {
        "payment_id": "pay_CAC02small3",
        "amount": 1500,
        "method": "netbanking",
        "invoice_id": "inv_small_0031",
        "customer": {"name": "Anil Traders", "email": "accounts@aniltraders.example",
                     "phone": "+919812340003"},
        "error": {"source": "customer", "step": "payment_initiation",
                  "reason": "invoice_overdue_15d",
                  "description": "Rs 15 invoice unpaid for 15 days"},
        "_why": "CAC_CEILING before the voice call - a Rs 2 call against a Rs 2.25 ceiling",
    },
    # Two payments from a contact who opted out on an earlier payment. The
    # registry is seeded at ingestion to represent consent withdrawn in the past.
    {
        "payment_id": "pay_OPT01prior1",
        "amount": 320000,
        "method": "card",
        "customer": {"name": "Priya Menon", "email": "priya.menon@example.com",
                     "phone": "+919812340004"},
        "error": {"source": "customer", "step": "payment_authentication",
                  "reason": "authentication_failed",
                  "description": "3DS challenge abandoned"},
        "consent": {"opted_out": True, "source": "dtmf_9"},
        "_why": "CONSENT_WITHDRAWN - this contact opted out on a previous payment",
    },
    {
        "payment_id": "pay_OPT02prior2",
        "amount": 145000,
        "method": "upi",
        "customer": {"name": "Priya Menon", "email": "priya.menon@example.com",
                     "phone": "+919812340004"},
        "error": {"source": "bank", "step": "payment_authorization",
                  "reason": "mandate_insufficient_funds",
                  "description": "Autopay mandate failed - low balance"},
        "_why": "CONSENT_WITHDRAWN - same contact, different payment, still suppressed",
    },
    # Overdue invoices arriving late at night. Voice is deferred until 09:00 IST;
    # WhatsApp is not, because a message wakes nobody.
    {
        "payment_id": "pay_QH001night1",
        "amount": 890000,
        "method": "netbanking",
        "invoice_id": "inv_night_0041",
        "customer": {"name": "Meridian Supplies", "email": "ap@meridian.example",
                     "phone": "+919812340005"},
        "error": {"source": "customer", "step": "payment_initiation",
                  "reason": "invoice_overdue_15d",
                  "description": "Invoice 15 days overdue, escalation raised at 23:10 IST"},
        "received_at_ist_hour": 23,
        "_why": "QUIET_HOURS_DEFERRED - voice call held until 09:00 IST",
    },
    {
        "payment_id": "pay_QH002night2",
        "amount": 560000,
        "method": "netbanking",
        "invoice_id": "inv_night_0042",
        "customer": {"name": "Kalyan Agro", "email": "finance@kalyanagro.example",
                     "phone": "+919812340006"},
        "error": {"source": "customer", "step": "payment_initiation",
                  "reason": "invoice_overdue_15d",
                  "description": "Invoice 15 days overdue, flagged at 02:40 IST"},
        "received_at_ist_hour": 2,
        "_why": "QUIET_HOURS_DEFERRED - overnight escalation held until morning",
    },
]

DEFAULTS = {
    "currency": "INR",
    "merchant_id": "merchant_A1b2C3",
    "subscription_id": None,
    "invoice_id": None,
    "recovery_state": "INGESTED",
}


def main() -> int:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    existing = {r["payment_id"] for r in dataset}

    added = 0
    for case in GUARD_CASES:
        if case["payment_id"] in existing:
            continue
        record = {**DEFAULTS, **case}
        dataset.append(record)
        added += 1

    DATASET.write_text(
        json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"Dataset now holds {len(dataset)} records ({added} added).")
    for case in GUARD_CASES:
        print(f"  {case['payment_id']:>20}  Rs {case['amount'] / 100:>9,.2f}  {case['_why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
