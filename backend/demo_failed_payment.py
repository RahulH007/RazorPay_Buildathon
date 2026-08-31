"""
Demo helper — send one signed `payment.failed` webhook to the running API.

This is exactly the request Razorpay's servers send when a card payment fails
on a merchant's checkout: same event name, same body shape, same
X-Razorpay-Signature header, verified with the same secret in backend/.env.

Used for the demo video so a failure can be produced on cue instead of hoping
a test-mode checkout fails with an error code the rule engine maps.

Run it from the `backend` directory while the API is running:

    python demo_failed_payment.py

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03.
"""

import hashlib
import hmac
import json
import random
import string
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "http://localhost:8000/api/webhooks/razorpay"
AMOUNT_PAISE = 45000          # Rs 450.00
CUSTOMER_NAME = "Priya Sharma"
CUSTOMER_PHONE = "+919876500777"
CUSTOMER_EMAIL = "priya@example.com"
ERROR_REASON = "authentication_failed"   # -> AUTH_FRICTION -> whatsapp_link


def read_secret() -> str:
    env = Path(__file__).parent / ".env"
    if not env.exists():
        sys.exit("backend/.env not found. Cannot sign the webhook.")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("RAZORPAY_WEBHOOK_SECRET="):
            return line.split("=", 1)[1].strip()
    sys.exit("RAZORPAY_WEBHOOK_SECRET is not set in backend/.env.")


def new_payment_id() -> str:
    alphabet = string.ascii_letters + string.digits
    return "pay_" + "".join(random.choice(alphabet) for _ in range(14))


def main() -> None:
    secret = read_secret()
    payment_id = new_payment_id()

    payload = {
        "event": "payment.failed",
        "account_id": "acc_RecoverOSDemo",
        "payload": {"payment": {"entity": {
            "id": payment_id,
            "amount": AMOUNT_PAISE,
            "currency": "INR",
            "method": "card",
            "email": CUSTOMER_EMAIL,
            "contact": CUSTOMER_PHONE,
            "error_source": "bank",
            "error_step": "payment_authorization",
            "error_reason": ERROR_REASON,
            "error_description": "Payment failed because the customer could not be authenticated by the bank.",
            "notes": {"customer_name": CUSTOMER_NAME},
        }}},
    }

    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    request = urllib.request.Request(
        API,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature,
        },
        method="POST",
    )

    print("-" * 62)
    print("  Sending a signed payment.failed webhook to RecoverOS")
    print("-" * 62)
    print(f"  payment id   : {payment_id}")
    print(f"  amount       : Rs {AMOUNT_PAISE / 100:,.2f}")
    print(f"  customer     : {CUSTOMER_NAME}  {CUSTOMER_PHONE}")
    print(f"  error reason : {ERROR_REASON}")
    print(f"  signature    : {signature[:32]}...  (HMAC-SHA256, verified by the API)")
    print("-" * 62)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(f"  HTTP {response.status}  {response.read().decode()}")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}  {e.read().decode()}")
        sys.exit(1)
    except urllib.error.URLError as e:
        sys.exit(f"  Could not reach {API} — is the API running? ({e.reason})")

    print("-" * 62)
    print(f"  Watch the Command Center. Record {payment_id} is being")
    print("  diagnosed, priced, authorized and sent a real Razorpay link.")
    print("-" * 62)


if __name__ == "__main__":
    main()
