"""Webhook autentifikatsiyasi — HMAC-SHA256 imzo tekshiruvi."""
from __future__ import annotations

import hashlib
import hmac
import time


def verify_webhook_signature(secret: str, body: bytes, signature: str,
                             timestamp: str | None = None,
                             max_age_seconds: int = 300) -> bool:
    """
    TradingView (yoki boshqa manba) webhook imzosini tekshiradi.
    Imzo: hex(hmac_sha256(secret, f"{timestamp}." + body))
    """
    if not secret or not signature:
        return False
    if timestamp:
        try:
            ts = int(timestamp)
        except ValueError:
            return False
        if abs(time.time() - ts) > max_age_seconds:
            return False
    payload = body if not timestamp else f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())
