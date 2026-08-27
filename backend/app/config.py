"""
RecoverOS Configuration Module
Loads environment variables and defines system constants.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import os
from datetime import timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

# --- Razorpay API ---
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "rzp_test_XXXXXXXXXXXXXX")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "XXXXXXXXXXXXXXXXXXXXXX")
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "XXXXXXXXXXXXXXXXXXXXXX")

# --- Gemini AI ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "XXXXXXXXXXXXXXXXXXXXXX")

# --- Sarvam AI TTS ---
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "XXXXXXXXXXXXXXXXXXXXXX")

# --- Database ---
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./recoveros.db")

# --- Public origin ---
# Where a payer's browser and Razorpay's webhooks can actually reach this
# service from the outside. The Payment Link callback was hardcoded to
# localhost, which resolves to the payer's own machine rather than to us, so a
# real customer paying on a phone landed nowhere. Configured rather than
# constant because the value is deployment-specific and, on a free ngrok tier,
# changes every time the tunnel restarts.
#
# The localhost default is deliberate: it keeps local development working, and
# nothing outward-facing happens in demo mode anyway.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

# Where Razorpay returns the payer after a Payment Link is paid. Settlement
# does NOT depend on this - that arrives on the signed webhook - so a stale
# value degrades the payer's landing page, never the recovery itself.
PAYMENT_LINK_CALLBACK_URL = f"{PUBLIC_BASE_URL}/api/webhooks/razorpay"

# --- System Constants ---
MAX_RETRIES = 3
CAC_CEILING_PERCENT = 15  # Max recovery cost as % of invoice GMV
SETTLEMENT_TIMEOUT_MINUTES = 30
CONFIDENCE_THRESHOLD = 0.7
CONFIDENCE_THRESHOLD_BP = int(CONFIDENCE_THRESHOLD * 10000)  # basis points
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"

# Deterministic simulation. Printed in every batch result header so a reported
# number can always be reproduced.
RECOVEROS_SEED = int(os.getenv("RECOVEROS_SEED", "20260825"))

# Assumed merchant gross margin. Recovering Rs 1,000 of GMV is not worth
# Rs 1,000 to the merchant - it is worth the margin on it. Stated here rather
# than buried inside a formula, because it decides whether we spend money.
MERCHANT_MARGIN_PERCENT = int(os.getenv("MERCHANT_MARGIN_PERCENT", "20"))

# Share of contacts left deliberately untreated so recovery attributable to
# this system can be separated from recovery that would have happened anyway.
HOLDOUT_PERCENT = int(os.getenv("HOLDOUT_PERCENT", "20"))

# --- Consent & Quiet Hours ---
# TRAI restricts promotional voice calls to 09:00-21:00 IST.
IST = timezone(timedelta(hours=5, minutes=30))
QUIET_HOURS_START_HOUR = 21  # 21:00 IST — no calls from here
QUIET_HOURS_END_HOUR = 9     # 09:00 IST — calls permitted from here

# --- Recovery Rate Probabilities (from blueprint §7) ---
RECOVERY_RATES = {
    "TRANSIENT_TECHNICAL": 0.85,
    "AUTH_FRICTION": 0.40,
    "MANDATE_BALANCE": 0.55,
    "B2B_RECEIVABLE": 0.50,
    "HARD_DECLINE": 0.00,
}

# --- Channel Costs in PAISE ---
# Integer paise, never float. These values feed ledger hashes, and float
# arithmetic is not reproducible across runtimes (0.1 + 0.2 != 0.3), which
# would break independent verification. Matches the existing convention for
# PaymentFailureRecord.amount. Divide by 100 only when rendering.
CHANNEL_COSTS_PAISE = {
    "TRANSIENT_TECHNICAL": 0,    # Silent retry — API call only
    "AUTH_FRICTION": 50,         # WhatsApp message (₹0.50)
    "MANDATE_BALANCE": 50,       # UPI resequence nudge (₹0.50)
    "B2B_RECEIVABLE": 200,       # Hinglish voice call (₹2.00)
    "HARD_DECLINE": 0,           # No action
}

# --- Recovery Channel Mapping ---
RECOVERY_CHANNELS = {
    "TRANSIENT_TECHNICAL": "silent_retry",
    "AUTH_FRICTION": "whatsapp_link",
    "MANDATE_BALANCE": "upi_resequence",
    "B2B_RECEIVABLE": "hinglish_voice",
    "HARD_DECLINE": None,
}

# --- Banned Phrases for Voice Scripts ---
BANNED_PHRASES = [
    "legal action", "court", "penalty", "fine", "sue",
    "arrest", "jail", "police", "blacklist", "block",
    "kanooni karwahi", "thana", "giraftaar",
]
