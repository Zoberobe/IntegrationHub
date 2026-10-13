"""Inspect a Stripe test-mode rejection using the order's existing idempotency key.

Print only non-secret error fields; do not print the API key or response body.
"""

import json
import sys

import httpx

from app.config import settings
from app.db import SessionLocal
from app.models import Order


def main(order_id):
    if not settings.stripe_secret_key.startswith(("sk_test_", "rk_test_")):
        raise SystemExit("Stripe test key is not configured")
    with SessionLocal() as session:
        order = session.get(Order, order_id)
        if order is None:
            raise SystemExit("Order not found")
        key = order.payment_idempotency_key
        data = {
            "amount": order.amount,
            "currency": order.currency,
            "description": order.description,
            "payment_method": "pm_card_visa",
            "allowed_payment_method_types[]": "card",
            "confirm": "true",
            "metadata[order_id]": order.id,
        }
    response = httpx.post(
        f"{settings.stripe_api_base}/v1/payment_intents",
        auth=(settings.stripe_secret_key, ""),
        headers={"Idempotency-Key": key},
        data=data,
        timeout=settings.payment_timeout_seconds,
    )
    try:
        error = response.json().get("error", {})
    except (ValueError, TypeError):
        error = {}
    print(json.dumps({
        "status_code": response.status_code,
        "error_type": error.get("type"),
        "error_code": error.get("code"),
        "error_param": error.get("param"),
        "decline_code": error.get("decline_code"),
        "message": str(error.get("message", "")).replace(settings.stripe_secret_key, "[redacted]")[:250],
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.diagnose_stripe ORDER_ID")
    main(sys.argv[1])
