"""Verify a completed order against a real Stripe test PaymentIntent."""

import json
import sys
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import IntegrationAttempt, Order, OrderState, SimulatedShipment, WebhookEvent


def main(order_id):
    if not settings.stripe_secret_key.startswith(("sk_test_", "rk_test_")):
        raise SystemExit("Configure a Stripe test secret key in .env")
    with SessionLocal() as session:
        order = session.get(Order, order_id)
        if order is None or not order.payment_intent_id:
            raise SystemExit("Order or PaymentIntent not found")
        expected = (order.id, order.payment_intent_id, order.amount, order.currency)
        state = order.state
        attempts = session.scalars(select(IntegrationAttempt).where(
            IntegrationAttempt.order_id == order_id,
            IntegrationAttempt.integration == "shipping",
        ).order_by(IntegrationAttempt.sequence)).all()
        shipping_attempts = [
            {"sequence": attempt.sequence, "outcome": attempt.outcome, "error_code": attempt.error_code}
            for attempt in attempts
        ]
        shipment_count = session.scalar(select(func.count()).select_from(SimulatedShipment).where(
            SimulatedShipment.order_id == order_id
        ))
        events = session.scalars(select(WebhookEvent).where(WebhookEvent.order_id == order_id)).all()

    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{settings.stripe_api_base}/v1/payment_intents/{expected[1]}",
            auth=(settings.stripe_secret_key, ""),
        )
    if response.status_code != 200:
        raise SystemExit(f"Stripe PaymentIntent lookup failed with HTTP {response.status_code}")
    intent = response.json()
    observed = (intent.get("metadata", {}).get("order_id"), intent.get("id"),
                intent.get("amount"), intent.get("currency"))
    assert observed == expected, (observed, expected)
    assert intent.get("status") == "succeeded"
    assert intent.get("livemode") is False
    assert state == OrderState.shipped
    assert [(a["sequence"], a["outcome"]) for a in shipping_attempts] == [
        (1, "temporary_failure"), (2, "succeeded")]
    assert shipment_count == 1 and len(events) == 1
    assert events[0].event_type == "payment_intent.succeeded"
    print(json.dumps({
        "order_id": order_id,
        "payment_intent_id": expected[1],
        "payment_intent_status": intent["status"],
        "stripe_livemode": intent["livemode"],
        "stripe_request_id": response.headers.get("Request-Id"),
        "webhook_event_id": events[0].id,
        "shipping_attempts": shipping_attempts,
        "shipment_count": shipment_count,
        "webhook_event_count": len(events),
        "final_state": state.value,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.stripe_payment_audit ORDER_ID")
    main(sys.argv[1])
