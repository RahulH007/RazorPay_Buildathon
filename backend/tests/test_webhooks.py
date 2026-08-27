"""
RecoverOS - original work of Rahul Hongekar (github.com/RahulH007)
Razorpay Buildathon, Track 03. Reuse without attribution is plagiarism.
"""

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
    """Local convenience, and only because demo mode cannot reach Razorpay."""
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "XXXXXXXXXXXXXXXXXXXXXX")
    monkeypatch.setattr(webhooks, "DEMO_MODE", True)

    assert webhooks.verify_webhook_signature(b"demo", "") is True


def test_real_mode_rejects_a_placeholder_secret(monkeypatch):
    """
    The verifier used to return True whenever the secret was unset, so a
    deployment that forgot RAZORPAY_WEBHOOK_SECRET accepted webhooks from
    anyone - and a forged payment.failed is an instruction to create a Payment
    Link and message a stranger.
    """
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "XXXXXXXXXXXXXXXXXXXXXX")
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)

    assert webhooks.verify_webhook_signature(b"anything", "") is False


def test_real_mode_rejects_a_missing_secret(monkeypatch):
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "")
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)

    assert webhooks.verify_webhook_signature(b"anything", "sig") is False


def test_real_mode_accepts_a_correctly_signed_body(monkeypatch):
    body = b'{"event":"payment.failed"}'
    secret = "a-real-looking-webhook-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", secret)
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)

    assert webhooks.verify_webhook_signature(body, signature) is True


def test_a_configured_secret_still_requires_a_signature(monkeypatch):
    monkeypatch.setattr(webhooks, "RAZORPAY_WEBHOOK_SECRET", "a-real-looking-secret")
    monkeypatch.setattr(webhooks, "DEMO_MODE", False)

    assert webhooks.verify_webhook_signature(b"body", "") is False
