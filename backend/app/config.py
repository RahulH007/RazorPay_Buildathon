"""
RecoverOS Configuration Module
Loads environment variables and defines system constants.
"""

import os
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

# --- System Constants ---
MAX_RETRIES = 3
CAC_CEILING_PERCENT = 15  # Max recovery cost as % of invoice GMV
SETTLEMENT_TIMEOUT_MINUTES = 30
CONFIDENCE_THRESHOLD = 0.7
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"

# --- Recovery Rate Probabilities (from blueprint §7) ---
RECOVERY_RATES = {
    "TRANSIENT_TECHNICAL": 0.85,
    "AUTH_FRICTION": 0.40,
    "MANDATE_BALANCE": 0.55,
    "B2B_RECEIVABLE": 0.50,
    "HARD_DECLINE": 0.00,
}

# --- Channel Costs in INR ---
CHANNEL_COSTS = {
    "TRANSIENT_TECHNICAL": 0.00,   # Silent retry — API call only
    "AUTH_FRICTION": 0.50,          # WhatsApp message
    "MANDATE_BALANCE": 0.50,        # UPI resequence nudge
    "B2B_RECEIVABLE": 2.00,         # Hinglish voice call
    "HARD_DECLINE": 0.00,           # No action
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
