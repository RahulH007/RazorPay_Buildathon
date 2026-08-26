"""
RecoverOS LLM Agent
Gemini integration for customer reply parsing, failure diagnosis, and
Hinglish script generation.

Every call goes through app.llm_cache, which records real responses and
replays them in demo mode. Nothing in this module invents a model response:
if there is no recorded answer and no API key, the call raises.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import json
import re

from app.config import GEMINI_API_KEY, CONFIDENCE_THRESHOLD, DEMO_MODE
from app import llm_cache
from app.schemas import FailureDiagnosis, ParsedIntent


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


def format_amount(amount_paise: int) -> str:
    """
    Render money from integer paise.

    Never `amount / 100`: a float formatted into a prompt, a script, or a
    ledger detail can differ across environments, and this string reaches both
    the customer and the hash preimage.
    """
    return f"₹{amount_paise // 100:,}.{amount_paise % 100:02d}"


# --- LLM Function 1: Customer Reply Parsing ---

PROMPT_VERSION_REPLY = 1
MODEL_REPLY = "gemini-3.6-flash"

REPLY_SYSTEM_PROMPT = """You are a payment recovery assistant for an Indian fintech platform.
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


def reply_inputs(record, reply_text: str) -> dict:
    """
    The cache key material for a reply parse.

    Only fields the model is actually shown belong here. Including anything
    volatile (a timestamp, a batch id) would make every run a cache miss.
    """
    return {
        "task": "parse_reply",
        "payment_id": record.payment_id,
        "amount_paise": record.amount,
        "error_reason": record.error_reason,
        "recovery_channel": record.recovery_channel or "pending",
        "reply": sanitize_input(reply_text),
    }


async def parse_customer_reply(record, reply_text: str) -> tuple[ParsedIntent, dict]:
    """
    Parse a customer's reply into structured intent.

    Returns the intent alongside the LLM metadata the ledger needs, so the
    caller can prove which model produced this reading and how confident it
    was. The caller decides what to DO about it - this function never acts.
    """
    inputs = reply_inputs(record, reply_text)
    user_prompt = f"""CONTEXT (from webhook data - do not modify these values):
- Payment ID: {inputs['payment_id']}
- Amount: {format_amount(record.amount)}
- Failure reason: {inputs['error_reason']}
- Recovery channel: {inputs['recovery_channel']}

CUSTOMER REPLY: "{inputs['reply']}"
"""

    response = llm_cache.call(
        model=MODEL_REPLY,
        prompt_version=PROMPT_VERSION_REPLY,
        inputs=inputs,
        contents=f"{REPLY_SYSTEM_PROMPT}\n\n{user_prompt}",
        response_mime_type="application/json",
    )

    parsed = _coerce_intent(response.text)
    metadata = {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
        "confidence": parsed.confidence,
    }
    return parsed, metadata


VALID_INTENTS = ("will_pay", "dispute", "opt_out", "request_delay", "unclear")


def _coerce_intent(raw_text: str) -> ParsedIntent:
    """
    Turn model output into a ParsedIntent.

    Malformed JSON becomes a low-confidence 'unclear' rather than an exception:
    an unreadable answer is a weak signal, not a system failure, and the
    confidence threshold downstream already knows what to do with a weak
    signal.
    """
    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        parsed = json.loads(match.group() if match else raw_text)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return ParsedIntent(
            intent="unclear", confidence=0.0, sentiment="neutral",
            requires_human=True, reasoning="Model returned unparseable output",
        )

    intent = parsed.get("intent", "unclear")
    if intent not in VALID_INTENTS:
        return ParsedIntent(
            intent="unclear", confidence=0.0, sentiment="neutral",
            requires_human=True,
            reasoning=f"Model returned unknown intent '{intent}'",
        )

    confidence = parsed.get("confidence", 0.5)
    try:
        confidence = min(max(float(confidence), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.0

    return ParsedIntent(
        intent=intent,
        confidence=confidence,
        extracted_date=parsed.get("extracted_date"),
        sentiment=parsed.get("sentiment", "neutral"),
        requires_human=bool(parsed.get("requires_human", False)),
        reasoning=parsed.get("reasoning", ""),
    )


# --- LLM Function 2: Failure Diagnosis (classifier slow path) ---

PROMPT_VERSION_DIAGNOSIS = 1
MODEL_DIAGNOSIS = "gemini-3.6-flash"

DIAGNOSIS_SYSTEM_PROMPT = """You are a payments reliability engineer working on Indian
payment failures (UPI, cards, NACH/e-mandate, netbanking). You are given the raw
error text a bank or gateway returned for a failed payment. Diagnose the root cause.

You MUST respond with valid JSON and nothing else.

root_cause_class MUST be exactly one of:
- TRANSIENT_TECHNICAL: bank or gateway side, likely to succeed on a plain retry
- AUTH_FRICTION: the customer failed an authentication step (OTP, 3DS, PIN)
- MANDATE_BALANCE: insufficient funds, expired instrument, or mandate presentation issue
- B2B_RECEIVABLE: an invoice a business has not paid, not a technical failure
- HARD_DECLINE: compliance, fraud, or a blocked instrument - must never be retried

RESPONSE SCHEMA:
{
  "root_cause_class": "<one of the five above>",
  "technical_explanation": "one or two sentences on what actually went wrong",
  "suggested_action": "what a human operator would do next",
  "confidence": 0.0-1.0
}"""

VALID_CLASSES = {
    "TRANSIENT_TECHNICAL", "AUTH_FRICTION", "MANDATE_BALANCE",
    "B2B_RECEIVABLE", "HARD_DECLINE",
}


def diagnosis_inputs(record) -> dict:
    return {
        "task": "diagnose_failure",
        "error_reason": record.error_reason,
        "error_description": sanitize_input(record.error_description or ""),
        "error_source": record.error_source or "unknown",
        "error_step": record.error_step or "unknown",
        "method": record.method,
    }


async def diagnose_failure(record) -> tuple[FailureDiagnosis, dict]:
    """
    Slow path: diagnose an error code the rule engine does not recognise.

    Note what this deliberately does NOT key on: payment_id, amount, customer.
    Two records with the same bank error get the same diagnosis and the same
    cache entry, because the diagnosis is a property of the error, not of the
    customer. That keeps the cache small and the reasoning inspectable.
    """
    inputs = diagnosis_inputs(record)
    user_prompt = f"""RAW FAILURE DATA:
- error.reason: {inputs['error_reason']}
- error.description: {inputs['error_description']}
- error.source: {inputs['error_source']}
- error.step: {inputs['error_step']}
- payment method: {inputs['method']}
"""

    response = llm_cache.call(
        model=MODEL_DIAGNOSIS,
        prompt_version=PROMPT_VERSION_DIAGNOSIS,
        inputs=inputs,
        contents=f"{DIAGNOSIS_SYSTEM_PROMPT}\n\n{user_prompt}",
        response_mime_type="application/json",
    )

    diagnosis = _coerce_diagnosis(response.text)
    metadata = {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
        "confidence": diagnosis.confidence,
    }
    return diagnosis, metadata


def _coerce_diagnosis(raw_text: str) -> FailureDiagnosis:
    """
    A class outside the enum is treated as zero confidence, not as an error.

    The model inventing a sixth failure class is exactly the case the
    confidence threshold exists for, so it is routed there rather than crashing
    a batch run.
    """
    try:
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        parsed = json.loads(match.group() if match else raw_text)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return FailureDiagnosis(
            root_cause_class="HARD_DECLINE",
            technical_explanation="Model returned unparseable output.",
            suggested_action="Human review.",
            confidence=0.0,
        )

    root_class = str(parsed.get("root_cause_class", "")).strip().upper()
    try:
        confidence = min(max(float(parsed.get("confidence", 0.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.0

    if root_class not in VALID_CLASSES:
        return FailureDiagnosis(
            root_cause_class="HARD_DECLINE",
            technical_explanation=str(parsed.get("technical_explanation", ""))[:500],
            suggested_action="Human review.",
            confidence=0.0,
        )

    return FailureDiagnosis(
        root_cause_class=root_class,
        technical_explanation=str(parsed.get("technical_explanation", ""))[:500],
        suggested_action=str(parsed.get("suggested_action", ""))[:500],
        confidence=confidence,
    )


# --- Output guards ----------------------------------------------------------

AMOUNT_PATTERN = re.compile(r"(?:Rs\.?|INR|₹)\s?([\d,]+(?:\.\d{1,2})?)")
LINK_PATTERN = re.compile(r"https?://\S+")


def verify_numbers(text: str, record, link_url: str | None = None) -> tuple[bool, str | None]:
    """
    Confirm the model did not invent a figure.

    The model writes the words. It never writes the numbers: every amount in
    generated copy must equal the record's amount, and every link must be one
    we created. A wrong amount in a recovery message is not a cosmetic defect -
    it is a payment instruction the customer may act on.
    """
    for raw in AMOUNT_PATTERN.findall(text):
        cleaned = raw.replace(",", "")
        try:
            rupees, _, paise = cleaned.partition(".")
            paise = (paise + "00")[:2] if paise else "00"
            found_paise = int(rupees) * 100 + int(paise)
        except ValueError:
            return False, f"Unparseable amount in generated text: '{raw}'"
        if found_paise != record.amount:
            return False, (
                f"Generated text states '{raw}' but the record amount is "
                f"{record.amount} paise"
            )

    for found_link in LINK_PATTERN.findall(text):
        stripped = found_link.rstrip(".,;:!?)")
        if link_url is None or stripped != link_url:
            return False, f"Generated text contains an unrecognised link: '{stripped}'"

    return True, None


# --- LLM Function 3: Per-customer WhatsApp copy ---

PROMPT_VERSION_WHATSAPP = 1
MODEL_WHATSAPP = "gemini-3.6-flash"

WHATSAPP_SYSTEM_PROMPT = """Write a short WhatsApp message in Hinglish (Hindi written in
Latin script, mixed with English) asking a customer to complete a failed payment.

Rules:
- Under 40 words.
- Polite. Never threatening, never shaming, never implying legal consequences.
- Use the customer's name and the exact amount given below. Do not alter the amount.
- Include the payment link exactly as given. Do not shorten or modify it.
- Explain in one clause why the payment failed, in plain language.
- Output the message text only. No preamble, no quotes, no markdown."""


def whatsapp_inputs(record, link_url: str) -> dict:
    return {
        "task": "whatsapp_message",
        "customer_name": record.customer_name,
        "amount_paise": record.amount,
        "failure_class": record.failure_class,
        "error_reason": record.error_reason,
        "link_url": link_url,
    }


async def generate_whatsapp_message(record, link_url: str) -> tuple[str, dict, str | None]:
    """
    Compose a per-customer WhatsApp message.

    Returns (text, llm_metadata, rejection_reason). A non-None rejection_reason
    means the generated text failed a guard and the returned text is the
    deterministic template instead.
    """
    inputs = whatsapp_inputs(record, link_url)
    fallback = _template_whatsapp(record, link_url)

    user_prompt = f"""CUSTOMER: {inputs['customer_name']}
EXACT AMOUNT (use verbatim): {format_amount(record.amount)}
FAILURE: {inputs['error_reason']} ({inputs['failure_class']})
PAYMENT LINK (use verbatim): {link_url}
"""

    try:
        response = llm_cache.call(
            model=MODEL_WHATSAPP,
            prompt_version=PROMPT_VERSION_WHATSAPP,
            inputs=inputs,
            contents=f"{WHATSAPP_SYSTEM_PROMPT}\n\n{user_prompt}",
        )
    except llm_cache.CacheMiss as e:
        # An unrecorded response is an expected, recoverable state: ship the
        # template and say so. Anything else - a retired model, a bad key, a
        # network failure - is a configuration fault, and swallowing it here
        # would report it as "the model wrote bad copy" while quietly burning
        # one live API call per record. Let it surface.
        return fallback, {}, f"Generation unavailable: {e.__class__.__name__}"

    text = response.text.strip()
    metadata = {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
    }

    try:
        _validate_script(text)
    except ValueError as e:
        return fallback, metadata, str(e)

    ok, reason = verify_numbers(text, record, link_url)
    if not ok:
        return fallback, metadata, reason

    return text, metadata, None


def _template_whatsapp(record, link_url: str) -> str:
    return (
        f"Namaste {record.customer_name} ji, aapka {format_amount(record.amount)} "
        f"ka payment complete nahi ho paya. Aap yahan se pay kar sakte hain: "
        f"{link_url}"
    )


# --- LLM Function 4: Hinglish Voice Script Generation ---

PROMPT_VERSION_SCRIPT = 1
MODEL_SCRIPT = "gemini-3.6-flash"

SCRIPT_SYSTEM_PROMPT = """Generate a polite, professional Hinglish voice script for a
payment recovery call. Conversational, respectful, under 30 seconds spoken.
Include the customer name, the exact amount given below, the invoice number, and
the DTMF options (press 1 to pay now, 2 to choose another date, 9 to opt out).

Rules:
- Never use threatening, shaming, or legal language.
- Use the amount exactly as given. Do not alter or round it.
- Output the script text only. No preamble, no quotes, no markdown."""


def script_inputs(record) -> dict:
    return {
        "task": "voice_script",
        "customer_name": record.customer_name,
        "amount_paise": record.amount,
        "invoice_id": record.invoice_id or "N/A",
        "method": record.method,
    }


async def generate_hinglish_script(record) -> tuple[str, dict, str | None]:
    """
    Compose a Hinglish voice script for this specific customer.

    Returns (script, llm_metadata, rejection_reason). A non-None rejection means
    the generated script failed a guard and the returned text is the
    deterministic template instead.
    """
    inputs = script_inputs(record)
    fallback = _generate_demo_script(
        record.customer_name, format_amount(record.amount), inputs["invoice_id"],
    )

    user_prompt = f"""CONTEXT:
- Customer Name: {inputs['customer_name']}
- Merchant Name: RecoverOS Merchant
- EXACT AMOUNT (use verbatim): {format_amount(record.amount)}
- Invoice ID: {inputs['invoice_id']}
- Payment Method: {inputs['method']}

OUTPUT: Plain text script in Hinglish, ready for TTS."""

    try:
        response = llm_cache.call(
            model=MODEL_SCRIPT,
            prompt_version=PROMPT_VERSION_SCRIPT,
            inputs=inputs,
            contents=f"{SCRIPT_SYSTEM_PROMPT}\n\n{user_prompt}",
        )
    except llm_cache.CacheMiss as e:
        # Only a cache miss falls back quietly - see generate_whatsapp_message.
        return fallback, {}, f"Generation unavailable: {e.__class__.__name__}"

    script = response.text.strip()
    metadata = {
        "model": response.model,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "latency_ms": response.latency_ms,
    }

    try:
        _validate_script(script)
    except ValueError as e:
        return fallback, metadata, str(e)

    ok, reason = verify_numbers(script, record)
    if not ok:
        return fallback, metadata, reason

    return script, metadata, None


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
