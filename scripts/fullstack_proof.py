"""Exercise PostgreSQL, the signed webhook endpoint, Redis, and the Celery worker.

The payment intent is seeded locally. This does not make a Stripe API call.
Run inside the API container: docker compose exec api python -m scripts.fullstack_proof
"""

import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import IntegrationAttempt, Order, OrderState, SimulatedShipment, WebhookEvent, now
from app.tasks import ship_order


def main():
    base_url = os.getenv("PROOF_API_BASE", "http://api:8000").rstrip("/")
    if not settings.stripe_webhook_secret:
        raise SystemExit("STRIPE_WEBHOOK_SECRET must be set")
    with httpx.Client(base_url=base_url, timeout=10) as client:
        created = client.post("/orders", json={
            "amount": 2500,
            "currency": "brl",
            "description": "PostgreSQL and Celery proof",
            "shipping_fail_once": True,
        })
        created.raise_for_status()
        order_id = created.json()["id"]
        intent_id = "pi_local_" + order_id

        with SessionLocal() as session:
            order = session.get(Order, order_id)
            order.state = OrderState.payment_pending
            order.payment_intent_id = intent_id
            order.payment_started_at = now()
            session.commit()

        event_id = "evt_local_" + uuid.uuid4().hex
        payload = json.dumps({
            "id": event_id,
            "type": "payment_intent.succeeded",
            "data": {"object": {
                "id": intent_id,
                "amount": 2500,
                "currency": "brl",
                "metadata": {"order_id": order_id},
            }},
        }, separators=(",", ":")).encode()
        timestamp = int(time.time())
        digest = hmac.new(
            settings.stripe_webhook_secret.encode(),
            str(timestamp).encode() + b"." + payload,
            hashlib.sha256,
        ).hexdigest()
        headers = {"stripe-signature": f"t={timestamp},v1={digest}"}
        first = client.post("/webhooks/stripe", content=payload, headers=headers)
        second = client.post("/webhooks/stripe", content=payload, headers=headers)
        first.raise_for_status()
        second.raise_for_status()
        assert first.json()["result"] == "processed"
        assert second.json()["result"] == "duplicate"

        states = []
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            response = client.get(f"/orders/{order_id}")
            response.raise_for_status()
            state = response.json()["state"]
            if not states or states[-1] != state:
                states.append(state)
            if state in ("shipped", "shipping_failed"):
                break
            time.sleep(0.5)
        assert states[-1] == "shipped", states

        # Redis may redeliver a task. The order must remain shipped.
        duplicate_tasks = [ship_order.delay(order_id), ship_order.delay(order_id)]
        duplicate_task_results = [task.get(timeout=20) for task in duplicate_tasks]
        assert duplicate_task_results == ["skipped", "skipped"]

    with SessionLocal() as session:
        attempts = session.scalars(
            select(IntegrationAttempt)
            .where(IntegrationAttempt.order_id == order_id, IntegrationAttempt.integration == "shipping")
            .order_by(IntegrationAttempt.sequence)
        ).all()
        shipment_count = session.scalar(
            select(func.count()).select_from(SimulatedShipment)
            .where(SimulatedShipment.order_id == order_id)
        )
        webhook_count = session.scalar(
            select(func.count()).select_from(WebhookEvent)
            .where(WebhookEvent.order_id == order_id)
        )
        final_order = session.get(Order, order_id)
        assert [attempt.outcome for attempt in attempts] == ["temporary_failure", "succeeded"]
        assert shipment_count == 1
        assert webhook_count == 1
        assert final_order.state == OrderState.shipped
        print(json.dumps({
            "order_id": order_id,
            "webhook_results": [first.json()["result"], second.json()["result"]],
            "states_observed": states,
            "duplicate_task_results": duplicate_task_results,
            "shipping_attempts": [
                {"sequence": attempt.sequence, "outcome": attempt.outcome, "error_code": attempt.error_code}
                for attempt in attempts
            ],
            "shipment_count": shipment_count,
            "webhook_event_count": webhook_count,
            "final_state": final_order.state.value,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "stripe_api_called": False,
        }, indent=2))


if __name__ == "__main__":
    main()
