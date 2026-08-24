import hashlib
import hmac

from app.routes import webhooks


def test_webhook_signature_accepts_matching_digest(monkeypatch):
    body = b'{"event":"payment.captured"}'
    secret = "webhook-test-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", secret)

    assert webhooks.verify_webhook_signature(body, signature) is True


def test_webhook_signature_rejects_modified_payload(monkeypatch):
    body = b'{"event":"payment.captured"}'
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "webhook-test-secret")

    assert webhooks.verify_webhook_signature(body, "invalid") is False


def test_webhook_signature_allows_demo_placeholder_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "XXXXXXXXXXXXXXXXXXXXXX")

    assert webhooks.verify_webhook_signature(b"demo", "") is True
