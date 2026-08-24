"""
RecoverOS LLM Agent
Gemini integration for customer reply parsing, Hinglish script generation,
and promise-to-pay date extraction.
"""

import json
import time
import re
from datetime import datetime, timezone

from app.config import GEMINI_API_KEY, CONFIDENCE_THRESHOLD, DEMO_MODE
from app.schemas import ParsedIntent


# --- Input Sanitization ---

def sanitize_input(text: str, max_length: int = 500) -> str:
    """Strip HTML, limit length, escape injection patterns."""
    if not text:
        return ""
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Remove potential prompt injection markers
    text = re.sub(r"(SYSTEM|ASSISTANT|USER)\s*:", "", text, flags=re.IGNORECASE)
    # Truncate
    return text[:max_length].strip()


# --- LLM Function 1: Customer Reply Parsing ---

async def parse_customer_reply(record, reply_text: str) -> ParsedIntent:
    """
    Parse a customer's reply to extract structured intent.
    Uses Gemini 2.0 Flash for fast multilingual inference.
    """
    sanitized_reply = sanitize_input(reply_text)
    start_time = time.time()

    # Build prompt with injected webhook data (amounts/IDs never LLM-generated)
    amount_display = f"₹{record.amount / 100:,.2f}"

    system_prompt = """You are a payment recovery assistant for an Indian fintech platform. 
Analyze the customer's reply to a recovery message and extract structured intent.
You MUST respond with valid JSON matching the schema below. Do not include any 
text outside the JSON object.

RESPONSE SCHEMA:
{
  "intent": "will_pay" | "dispute" | "opt_out" | "request_delay" | "unclear",
  "confidence": 0.0-1.0,
  "extracted_date": "YYYY-MM-DD" | null,
  "sentiment": "positive" | "neutral" | "negative",
  "requires_human": true | false,
  "reasoning": "one-line explanation of classification"
}"""

    user_prompt = f"""CONTEXT (from webhook data — do not modify these values):
- Payment ID: {record.payment_id}
- Amount: {amount_display}
- Failure reason: {record.error_reason}
- Recovery channel: {record.recovery_channel or 'pending'}

CUSTOMER REPLY: "{sanitized_reply}"
"""

    try:
        if not DEMO_MODE and GEMINI_API_KEY and "XXXX" not in GEMINI_API_KEY:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=f"{system_prompt}\n\n{user_prompt}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ParsedIntent,
                ),
            )
            response_text = response.text.strip()
            # Extract JSON from response
            json_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
            else:
                parsed = json.loads(response_text)

            latency_ms = int((time.time() - start_time) * 1000)

            return ParsedIntent(
                intent=parsed.get("intent", "unclear"),
                confidence=parsed.get("confidence", 0.5),
                extracted_date=parsed.get("extracted_date"),
                sentiment=parsed.get("sentiment", "neutral"),
                requires_human=parsed.get("requires_human", False),
                reasoning=parsed.get("reasoning", "LLM classification"),
            )
        else:
            # Demo mode: simulate LLM response
            return _simulate_reply_parsing(sanitized_reply)

    except Exception as e:
        print(f"[WARN] LLM parse_customer_reply failed: {e}")
        return ParsedIntent(
            intent="unclear",
            confidence=0.3,
            sentiment="neutral",
            requires_human=True,
            reasoning=f"LLM call failed: {str(e)[:100]}",
        )


def _simulate_reply_parsing(reply_text: str) -> ParsedIntent:
    """Demo mode: rule-based simulation of LLM parsing."""
    reply_lower = reply_text.lower() if reply_text else ""

    # Opt-out detection
    opt_out_words = ["stop", "cancel", "no", "mat karo", "band karo", "nahi"]
    if any(re.search(rf"\b{re.escape(word)}\b", reply_lower) for word in opt_out_words):
        return ParsedIntent(
            intent="opt_out", confidence=0.95, sentiment="negative",
            reasoning="Customer expressed opt-out intent",
        )

    # Dispute and delay take precedence over a generic payment mention.
    dispute_words = ["dispute", "wrong", "fraud", "galat", "refund"]
    if any(word in reply_lower for word in dispute_words):
        return ParsedIntent(
            intent="dispute", confidence=0.88, sentiment="negative",
            requires_human=True,
            reasoning="Customer raised a dispute",
        )

    delay_words = ["delay", "later", "next week", "salary", "1st", "5th", "baad mein", "kal"]
    if any(word in reply_lower for word in delay_words):
        return ParsedIntent(
            intent="request_delay", confidence=0.85, sentiment="neutral",
            extracted_date=None,
            reasoning="Customer requested payment delay",
        )

    # Will pay
    pay_words = ["pay", "kar dunga", "bhej deta", "abhi karta", "payment", "upi"]
    if any(word in reply_lower for word in pay_words):
        return ParsedIntent(
            intent="will_pay", confidence=0.90, sentiment="positive",
            reasoning="Customer agreed to pay",
        )

    return ParsedIntent(
        intent="unclear", confidence=0.4, sentiment="neutral",
        requires_human=True,
        reasoning="Could not determine clear intent from reply",
    )


# --- LLM Function 2: Hinglish Voice Script Generation ---

async def generate_hinglish_script(record) -> str:
    """
    Generate a contextual Hinglish voice script for payment recovery calls.
    Uses Gemini 2.5 Pro for natural script generation.
    """
    amount_display = f"₹{record.amount / 100:,.2f}"
    customer_name = record.customer_name
    merchant_name = "RecoverOS Merchant"
    invoice_id = record.invoice_id or "N/A"

    system_prompt = """Generate a polite, professional Hinglish voice script for a payment 
recovery call. The script should be conversational, respectful, and under 
30 seconds when spoken. Include the customer name, amount, invoice number, 
and DTMF options. Do not include any threatening language."""

    user_prompt = f"""CONTEXT:
- Customer Name: {customer_name}
- Merchant Name: {merchant_name}
- Amount: {amount_display}
- Invoice ID: {invoice_id}
- Payment Method: {record.method}

OUTPUT: Plain text script in Hinglish (Hindi + English mix), ready for TTS."""

    try:
        if not DEMO_MODE and GEMINI_API_KEY and "XXXX" not in GEMINI_API_KEY:
            from google import genai

            client = genai.Client(api_key=GEMINI_API_KEY)
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=f"{system_prompt}\n\n{user_prompt}",
            )
            script = response.text.strip()
            # Validate against banned phrases
            _validate_script(script)
            return script
        else:
            # Demo mode: return template script
            return _generate_demo_script(customer_name, amount_display, invoice_id)

    except Exception as e:
        print(f"[WARN] LLM generate_hinglish_script failed: {e}")
        return _generate_demo_script(customer_name, amount_display, invoice_id)


def _generate_demo_script(customer_name: str, amount: str, invoice_id: str) -> str:
    """Generate a demo Hinglish script without LLM."""
    return (
        f"Namaste {customer_name} ji, main RecoverOS Merchant ki taraf se bol raha hoon. "
        f"Aapka {amount} ka payment abhi pending hai"
        f"{f', invoice #{invoice_id}' if invoice_id != 'N/A' else ''}. "
        f"Agar aap abhi payment karna chahein toh 1 dabayein — "
        f"hum aapko turant UPI payment link bhej denge. "
        f"Agar kisi aur date pe karna hai toh 2 dabayein. "
        f"Agar aap ye calls nahi chahte toh 9 dabayein. Dhanyavaad!"
    )


def _validate_script(script: str):
    """Validate script against banned phrases."""
    from app.config import BANNED_PHRASES
    script_lower = script.lower()
    for phrase in BANNED_PHRASES:
        if phrase in script_lower:
            raise ValueError(f"Script contains banned phrase: '{phrase}'")


# --- LLM Function 3: Promise-to-Pay Date Extraction ---

async def extract_p2p_date(record, reply_text: str) -> str | None:
    """
    Extract a promise-to-pay date from natural language.
    Handles Hindi/English: "next Friday", "salary aane do", "1st ko kar dunga"
    """
    sanitized = sanitize_input(reply_text)

    try:
        if not DEMO_MODE and GEMINI_API_KEY and "XXXX" not in GEMINI_API_KEY:
            from google import genai

            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = f"""Extract the promised payment date from this customer reply.
Reply with ONLY a date in YYYY-MM-DD format, or "null" if no date mentioned.

Today's date: {datetime.now().strftime('%Y-%m-%d')}
Customer reply: "{sanitized}"
"""
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
            )
            result = response.text.strip()
            if result and result != "null":
                return result
            return None
        else:
            # Demo mode: simple date extraction
            return _extract_demo_date(sanitized)

    except Exception as e:
        print(f"[WARN] LLM extract_p2p_date failed: {e}")
        return None


def _extract_demo_date(text: str) -> str | None:
    """Simple demo date extraction from common patterns."""
    text_lower = text.lower()
    now = datetime.now()

    if "1st" in text_lower or "pehli" in text_lower:
        # Next 1st of month
        if now.day > 1:
            month = now.month + 1 if now.month < 12 else 1
            year = now.year if now.month < 12 else now.year + 1
        else:
            month, year = now.month, now.year
        return f"{year}-{month:02d}-01"

    if "5th" in text_lower or "paanch" in text_lower:
        if now.day > 5:
            month = now.month + 1 if now.month < 12 else 1
            year = now.year if now.month < 12 else now.year + 1
        else:
            month, year = now.month, now.year
        return f"{year}-{month:02d}-05"

    if "next week" in text_lower or "agle hafte" in text_lower:
        from datetime import timedelta
        next_week = now + timedelta(days=7)
        return next_week.strftime("%Y-%m-%d")

    if "tomorrow" in text_lower or "kal" in text_lower:
        from datetime import timedelta
        tomorrow = now + timedelta(days=1)
        return tomorrow.strftime("%Y-%m-%d")

    return None
