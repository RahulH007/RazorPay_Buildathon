"""
RecoverOS Webhook Routes
POST /api/webhooks/razorpay — Razorpay webhook ingestion with HMAC-SHA256 verification.
GET  /api/webhooks/razorpay — the payer's browser landing after a Payment Link,
                              informational only; it never settles anything.

RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

import hmac
import hashlib

from fastapi import APIRouter, BackgroundTasks, Request, HTTPException
from fastapi.responses import HTMLResponse

from app.config import DEMO_MODE, RAZORPAY_WEBHOOK_SECRET
from app.database import SessionLocal
from app.event_adapter import ingest_and_process, normalize_razorpay_payment_failed
from app.settlement import (
    handle_invoice_paid,
    handle_payment_captured,
    handle_payment_link_paid,
)

router = APIRouter()


async def _process_payment_failed(normalized: dict) -> None:
    """Background half of live ingestion, with its own session."""
    db = SessionLocal()
    try:
        await ingest_and_process(db, normalized)
    except Exception as e:  # noqa: BLE001 - a webhook must not crash the app
        print(f"[ERROR] Live ingestion failed for "
              f"{normalized.get('payment_id')}: {type(e).__name__}: {e}")
    finally:
        db.close()


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """
    Verify Razorpay's HMAC-SHA256 signature over the exact bytes received.

    Fails closed outside demo mode. The previous version returned True whenever
    the secret was missing or still a placeholder, which meant a deployment
    that simply forgot to set RAZORPAY_WEBHOOK_SECRET would accept unsigned
    webhooks from anyone - and a forged payment.failed is an instruction to
    create a Payment Link and message a stranger.

    Demo mode keeps the old convenience so local work needs no secret, and only
    because demo mode cannot reach the live Razorpay API at all.
    """
    secret_is_usable = bool(RAZORPAY_WEBHOOK_SECRET) and "XXXX" not in RAZORPAY_WEBHOOK_SECRET

    if not secret_is_usable:
        if DEMO_MODE:
            return True
        print("[SECURITY] Rejecting webhook: RAZORPAY_WEBHOOK_SECRET is missing "
              "or still a placeholder, and DEMO_MODE is false.")
        return False

    if not signature:
        return False

    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


@router.get("/webhooks/razorpay", response_class=HTMLResponse)
async def payment_link_return(request: Request):
    """
    Where Razorpay sends the payer's browser after a Payment Link is paid.

    This is a landing page and nothing else. It reads the query string only to
    show the payer something sensible, and it deliberately changes no state:

      * the parameters live in a URL the payer can edit, so treating them as
        proof of payment would let anyone mark a record recovered by typing a
        different id into the address bar;
      * settlement already has an authenticated path - the signed
        payment_link.paid webhook, checked against the RazorpayPaymentLink row
        this system wrote itself.

    So the answer to "did this recover the payment?" is: no, and it must not.
    The webhook did that, one second earlier, over a channel the payer cannot
    forge. Before this handler existed the redirect hit the POST-only route and
    returned 405, which worked but showed the payer a raw error.
    """
    q = request.query_params
    status = (q.get("razorpay_payment_link_status") or "").lower()
    link_id = q.get("razorpay_payment_link_id") or ""
    payment_id = q.get("razorpay_payment_id") or ""

    paid = status == "paid"
    headline = "Payment received" if paid else "Payment not completed"
    blurb = (
        "Thank you. Your payment has been received and the merchant has been notified."
        if paid else
        "This payment was not completed. If you were charged, it will be reversed automatically."
    )
    accent = "#12B76A" if paid else "#B54708"

    # Escaped, because these values come from the query string.
    def esc(v: str) -> str:
        return (v.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))[:64]

    reference = ""
    if link_id or payment_id:
        reference = (
            f'<p class="ref">Reference: {esc(link_id)}'
            f'{" &middot; " + esc(payment_id) if payment_id else ""}</p>'
        )

    return HTMLResponse(
        status_code=200,
        content=f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{headline}</title>
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center;
         justify-content:center; background:#F7F8FA; color:#162F56;
         font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .card {{ background:#fff; border:1px solid #E5E9F0; border-radius:16px;
          padding:40px 36px; max-width:420px; text-align:center;
          box-shadow:0 2px 20px rgba(0,0,0,.04); }}
  .dot {{ width:44px; height:44px; border-radius:50%; background:{accent};
         margin:0 auto 20px; }}
  h1 {{ font-size:20px; margin:0 0 10px; }}
  p {{ font-size:14px; line-height:1.6; color:#5A6B87; margin:0; }}
  .ref {{ margin-top:20px; font-family:ui-monospace,monospace; font-size:11px;
         color:#94A3B8; word-break:break-all; }}
</style></head>
<body><div class="card">
  <div class="dot"></div>
  <h1>{headline}</h1>
  <p>{blurb}</p>
  {reference}
</div></body></html>""",
    )


@router.post("/webhooks/razorpay")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives Razorpay webhook events.
    Verifies HMAC-SHA256 signature, then dispatches to appropriate handler.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception:
        # The signature checked out, so these really are bytes Razorpay sent -
        # but they are not JSON. Left unhandled this surfaced as a 500 with a
        # traceback; a body that cannot be parsed is a client error, and saying
        # so plainly beats an opaque server error in the webhook log.
        raise HTTPException(status_code=400, detail="webhook body is not valid JSON")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="webhook body is not a JSON object")

    event = payload.get("event", "")

    db = SessionLocal()
    try:
        if event == "payment.captured":
            payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
            payment_id = payment.get("id", "")
            result = await handle_payment_captured(db, payment_id, payload)
            return {"status": "processed", "event": event, "result": result}

        elif event == "payment_link.paid":
            # The reliable correlation path: the event names the Payment Link,
            # and this system holds a row proving which record it belongs to.
            result = await handle_payment_link_paid(db, payload)
            return {"status": "processed", "event": event, "result": result}

        elif event == "invoice.paid":
            invoice = payload.get("payload", {}).get("invoice", {}).get("entity", {})
            invoice_id = invoice.get("id", "")
            result = await handle_invoice_paid(db, invoice_id, payload)
            return {"status": "processed", "event": event, "result": result}

        elif event == "payment.failed":
            normalized = normalize_razorpay_payment_failed(payload)
            if normalized is None:
                # Reject before anything durable is written. A payload we
                # cannot identify is not a record we can meaningfully store.
                #
                # 400 rather than a 200 acknowledgement: this body will never
                # become valid, so a redelivery of it is pointless and the
                # status should say so plainly to whoever is looking at the
                # webhook log.
                raise HTTPException(
                    status_code=400,
                    detail="malformed payment.failed payload: missing payment id, amount or account",
                )

            # Acknowledge immediately and do the work after. Razorpay retries on
            # a slow response, and classification can involve a model call -
            # holding the connection open for that invites duplicate deliveries.
            background_tasks.add_task(_process_payment_failed, normalized)
            return {"status": "accepted", "event": event,
                    "payment_id": normalized["payment_id"]}

        else:
            return {"status": "ignored", "event": event}
    finally:
        db.close()
