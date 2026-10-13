"""Replay a Stripe-origin test event after its first CLI delivery.

Run inside the API container after the order is shipped:
    docker compose exec api python -m scripts.stripe_replay ORDER_ID

The script retrieves the stored event ID from PostgreSQL, fetches that event
from Stripe, signs a local replay with the CLI listener secret, and verifies
that the order still has one event record and one shipment.
"""

import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import Order, OrderState, SimulatedShipment, WebhookEvent


def counts(session, order_id):
    events = session.scalar(select(func.count()).select_from(WebhookEvent).where(WebhookEvent.order_id == order_id))
    shipments = session.scalar(select(func.count()).select_from(SimulatedShipment).where(SimulatedShipment.order_id == order_id))
    return events, shipments


def main(order_id):
    if not settings.stripe_secret_key.startswith(("sk_test_", "rk_test_")):
        raise SystemExit("Configure a Stripe test secret key in .env first")
    if not settings.stripe_webhook_secret.startswith("whsec_"):
        raise SystemExit("Configure the active Stripe CLI listener secret in .env first")

    with SessionLocal() as session:
        order = session.get(Order, order_id)
        if order is None:
            raise SystemExit("Order not found")
        event = session.scalar(select(WebhookEvent).where(
            WebhookEvent.order_id == order_id,
            WebhookEvent.event_type == "payment_intent.succeeded",
        ))
        if event is None or order.state != OrderState.shipped:
            raise SystemExit("Wait for the original Stripe webhook and completed shipment")
        before = counts(session, order_id)
        expected = (order.payment_intent_id, order.amount, order.currency)
        event_id = event.id

    with httpx.Client(timeout=10) as client:
        response = client.get(
            f"{settings.stripe_api_base}/v1/events/{event_id}",
            auth=(settings.stripe_secret_key, ""),
        )
        if response.status_code != 200:
            raise SystemExit(f"Stripe event lookup failed with HTTP {response.status_code}")
        payload = response.content
        body = response.json()
        obj = body.get("data", {}).get("object", {})
        observed = (obj.get("id"), obj.get("amount"), obj.get("currency"))
        if (body.get("id") != event_id or body.get("type") != "payment_intent.succeeded"
                or obj.get("metadata", {}).get("order_id") != order_id
                or observed != expected):
            raise SystemExit("Stripe event does not match the stored order")

        timestamp = int(time.time())
        digest = hmac.new(
            settings.stripe_webhook_secret.encode(),
            str(timestamp).encode() + b"." + payload,
            hashlib.sha256,
        ).hexdigest()
        base_url = os.getenv("PROOF_API_BASE", "http://api:8000").rstrip("/")
        replay = client.post(
            f"{base_url}/webhooks/stripe",
            content=payload,
            headers={"Stripe-Signature": f"t={timestamp},v1={digest}"},
        )
        replay.raise_for_status()
        result = replay.json().get("result")

    with SessionLocal() as session:
        after = counts(session, order_id)
        state = session.get(Order, order_id).state
    assert result == "duplicate", result
    assert before == after == (1, 1), (before, after)
    assert state == OrderState.shipped, state
    print(json.dumps({
        "order_id": order_id,
        "stripe_event_id": event_id,
        "replay_result": result,
        "before": {"webhook_events": before[0], "shipments": before[1]},
        "after": {"webhook_events": after[0], "shipments": after[1]},
        "final_state": state.value,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "stripe_api_called": True,
        "replay_source": "Stripe event fetched by ID and signed locally",
    }, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.stripe_replay ORDER_ID")
    main(sys.argv[1])
