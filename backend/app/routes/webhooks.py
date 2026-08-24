"""
RecoverOS Webhook Routes
POST /api/webhooks/razorpay — Razorpay webhook ingestion with HMAC-SHA256 verification.
"""

import hmac
import hashlib

from fastapi import APIRouter, Request, HTTPException

from app.config import RAZORPAY_WEBHOOK_SECRET
from app.database import SessionLocal
from app.settlement import handle_payment_captured, handle_invoice_paid

router = APIRouter()


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Verify Razorpay webhook HMAC-SHA256 signature."""
    if not RAZORPAY_WEBHOOK_SECRET or "XXXX" in RAZORPAY_WEBHOOK_SECRET:
        # Skip verification in demo mode
        return True

    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


@router.post("/webhooks/razorpay")
async def receive_webhook(request: Request):
    """
    Receives Razorpay webhook events.
    Verifies HMAC-SHA256 signature, then dispatches to appropriate handler.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event = payload.get("event", "")

    db = SessionLocal()
    try:
        if event == "payment.captured":
            payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
            payment_id = payment.get("id", "")
            result = await handle_payment_captured(db, payment_id, payload)
            return {"status": "processed", "event": event, "result": result}

        elif event == "invoice.paid":
            invoice = payload.get("payload", {}).get("invoice", {}).get("entity", {})
            invoice_id = invoice.get("id", "")
            result = await handle_invoice_paid(db, invoice_id, payload)
            return {"status": "processed", "event": event, "result": result}

        elif event == "payment.failed":
            # Payment failure — could be ingested via webhook
            return {"status": "acknowledged", "event": event, "message": "Use POST /api/batch/run for batch ingestion"}

        else:
            return {"status": "ignored", "event": event}
    finally:
        db.close()
