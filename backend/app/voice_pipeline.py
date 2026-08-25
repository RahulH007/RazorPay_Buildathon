"""
RecoverOS Voice Pipeline
Hinglish script generation → TTS synthesis → audio delivery.
"""

import os
import uuid
import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import PaymentFailureRecord
from app.llm_agent import generate_hinglish_script
from app.state_machine import log_audit
from app.config import SARVAM_API_KEY, DEMO_MODE


async def generate_voice_audio(db: Session, record: PaymentFailureRecord) -> str:
    """
    Full pipeline: LLM script → Sarvam TTS → audio URL.
    In demo mode, returns a simulated audio URL.
    """
    # 1. Generate Hinglish script via Gemini
    script = await generate_hinglish_script(record)

    # 2. Log script generation
    log_audit(
        db, record,
        action="VOICE_SCRIPT_GENERATED",
        actor="llm_agent",
        details=f"Hinglish script: {script[:200]}...",
    )

    # 3. Synthesize via Sarvam AI TTS or mock
    if not DEMO_MODE and SARVAM_API_KEY and "XXXX" not in SARVAM_API_KEY:
        audio_url = await sarvam_tts(script)
    else:
        audio_url = mock_tts(script, record.payment_id)

    return audio_url


async def sarvam_tts(script: str, voice: str = "saaras", lang: str = "hi-IN") -> str:
    """
    Synthesize speech using Sarvam AI TTS API.
    Returns URL of generated audio file.
    """
    try:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.sarvam.ai/text-to-speech",
                headers={
                    "Authorization": f"Bearer {SARVAM_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "text": script,
                    "model": voice,
                    "language": lang,
                    "format": "mp3",
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("audio_url", mock_tts(script, "fallback"))
    except Exception as e:
        print(f"[WARN] Sarvam TTS failed: {e}")
        return mock_tts(script, "fallback")


def mock_tts(script: str, payment_id: str) -> str:
    """
    Mock TTS: generate a deterministic audio URL for demo purposes.
    In a real demo, this could save a browser-native SpeechSynthesis recording.
    """
    # Generate deterministic ID from script content
    script_hash = hashlib.md5(script.encode()).hexdigest()[:8]
    return f"/api/voice/{payment_id}?script_hash={script_hash}"


# --- Voice Call Response Handling ---

async def handle_dtmf_response(
    db: Session,
    record: PaymentFailureRecord,
    dtmf_key: str,
) -> dict:
    """
    Handle DTMF button press from voice call.
    1 = Pay Now → Send SMS payment link
    2 = Delay  → Log P2P date request
    9 = Stop   → Opt-out halt
    """
    from app.state_machine import transition_state

    if dtmf_key == "1":
        # Pay Now → send payment link via SMS
        log_audit(
            db, record,
            action="DTMF_PAY_NOW",
            actor="customer",
            details="Customer pressed 1 (Pay Now) — sending SMS payment link",
        )
        return {
            "response": "pay_now",
            "action": "SMS payment link will be sent",
            "link": f"https://rzp.io/i/demo_{record.payment_id[-8:]}",
        }

    elif dtmf_key == "2":
        # Delay → extract P2P date
        from app.llm_agent import extract_p2p_date
        p2p_date = await extract_p2p_date(record, "next salary date")

        log_audit(
            db, record,
            action="DTMF_DELAY_P2P",
            actor="customer",
            details=f"Customer pressed 2 (Delay) — P2P date: {p2p_date or 'to be confirmed'}",
        )
        return {
            "response": "delay",
            "p2p_date": p2p_date,
            "action": "Promise-to-pay logged, follow-up scheduled",
        }

    elif dtmf_key == "9":
        # Opt-out -> registry first, then halt this payment.
        # Order matters: the registry entry is what protects the customer's
        # *other* payments, so it must be written even if the transition below
        # is a no-op because this record is already terminal.
        from app.consent import record_opt_out

        record_opt_out(
            db,
            phone=record.customer_phone,
            source="dtmf_9",
            payment_id=record.payment_id,
            channel="all",
            batch_id=record.batch_id,
        )
        log_audit(
            db, record,
            action="DTMF_OPT_OUT",
            actor="customer",
            details="Customer pressed 9 (Opt-Out) — consent withdrawn for all channels",
        )
        if record.recovery_state not in ("RECOVERED", "FAILED_STOPPED"):
            await transition_state(
                db, record,
                to_state="FAILED_STOPPED",
                actor="customer",
                details="Customer opted out via DTMF (pressed 9)",
            )
        return {
            "response": "opt_out",
            "action": "All recovery actions halted — opt-out recorded",
            "scope": "Suppression applies to every future payment from this contact",
        }

    else:
        return {
            "response": "invalid",
            "action": f"Invalid DTMF key: {dtmf_key}",
        }
