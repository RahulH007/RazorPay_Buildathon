"""
RecoverOS Razorpay Client

The single gate between this system and Razorpay's live API.

Every real API call is allowed only when all four of these hold:

    DEMO_MODE is false
    source == "razorpay_webhook"
    RAZORPAY_KEY_ID is a real value, not the placeholder
    RAZORPAY_KEY_SECRET is a real value, not the placeholder

The `source` condition is the important one and it is easy to under-value.
DEMO_MODE alone is a single global switch: flip it once, for any reason, and
the synthetic batch of 65 seeded records would start creating real Payment
Links and sending real notifications to phone numbers that belong to nobody.
Requiring the caller to name where the work originated means the demo pipeline
cannot reach the network even with live credentials loaded and demo mode off,
because it never carries that source.

There is deliberately no RAZORPAY_TEST_ACTIONS_ENABLED or similar switch: one
more global flag would be one more thing to set wrongly.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

from typing import Optional

from app.config import DEMO_MODE, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

# The only source permitted to reach the live API. A record ingested from a
# signed Razorpay webhook describes a payment that really failed, for a
# customer who really exists.
LIVE_SOURCE = "razorpay_webhook"

# Everything the simulator, the dataset and the dashboard produce.
SYNTHETIC_SOURCE = "synthetic"

# config.py ships placeholders of this shape so the app starts without secrets.
PLACEHOLDER_MARKER = "XXXX"


class RazorpayNotConfigured(RuntimeError):
    """Raised when a live call is attempted without a usable configuration."""


def _is_real_credential(value: Optional[str]) -> bool:
    return bool(value) and PLACEHOLDER_MARKER not in value


def is_configured(source: str) -> bool:
    """
    True when a real Razorpay call from this source would be permitted.

    Callers use this to decide whether to take the live path at all, so it must
    never raise - a missing secret is an expected state, not an error.
    """
    if DEMO_MODE:
        return False
    if source != LIVE_SOURCE:
        return False
    return _is_real_credential(RAZORPAY_KEY_ID) and _is_real_credential(RAZORPAY_KEY_SECRET)


def get_client(source: str):
    """
    Build an authenticated Razorpay client, or refuse.

    Raises rather than returning None so that a caller who skips is_configured
    fails loudly instead of calling a method on None somewhere further down.
    """
    if not is_configured(source):
        raise RazorpayNotConfigured(
            f"Refusing to build a Razorpay client: "
            f"demo_mode={DEMO_MODE}, source={source!r}, "
            f"credentials_present={_is_real_credential(RAZORPAY_KEY_ID) and _is_real_credential(RAZORPAY_KEY_SECRET)}. "
            f"A live client requires DEMO_MODE=false, source={LIVE_SOURCE!r}, "
            f"and real RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET values."
        )

    import razorpay

    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def create_payment_link(source: str, payload: dict) -> dict:
    """
    Create a real Razorpay Payment Link.

    Returns Razorpay's response dict. Raises RazorpayNotConfigured when the gate
    is closed, and lets any API error propagate so the caller can decide what to
    record - a failed creation must not leave a correlation row behind claiming
    a link exists.

    This function is the single seam the test suite patches. Nothing else in the
    codebase may call `razorpay.Client(...).payment_link.create` directly.
    """
    client = get_client(source)
    return client.payment_link.create(payload)
