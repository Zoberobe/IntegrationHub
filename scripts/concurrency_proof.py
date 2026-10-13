"""Demonstrate PostgreSQL row locking for concurrent shipping attempts.

Stop Beat during this focused check, then run inside the API container:
    docker compose exec api python -m scripts.concurrency_proof
"""

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from sqlalchemy import func, select

from app.db import SessionLocal
from app.integrations import SimulatedShippingGateway
from app.models import IntegrationAttempt, Order, OrderState, ShippingJob, SimulatedShipment, now
from app.services import process_shipping


class SlowShippingGateway:
    def create_shipment(self, session, order, key):
        time.sleep(0.75)
        return SimulatedShippingGateway().create_shipment(session, order, key)


def main():
    base_url = os.getenv("PROOF_API_BASE", "http://api:8000").rstrip("/")
    with httpx.Client(base_url=base_url, timeout=10) as client:
        response = client.post("/orders", json={
            "amount": 2500,
            "currency": "brl",
            "description": "PostgreSQL row-lock proof",
            "shipping_fail_once": False,
        })
        response.raise_for_status()
        order_id = response.json()["id"]

    with SessionLocal() as session:
        order = session.get(Order, order_id)
        order.state = OrderState.shipping_pending
        order.payment_intent_id = "pi_local_" + uuid.uuid4().hex
        session.add(ShippingJob(order_id=order_id, due_at=now()))
        session.commit()

    barrier = threading.Barrier(4)

    def attempt():
        barrier.wait(timeout=10)
        with SessionLocal() as session:
            return process_shipping(session, order_id, SlowShippingGateway())

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: attempt(), range(4)))

    with SessionLocal() as session:
        shipment_count = session.scalar(
            select(func.count()).select_from(SimulatedShipment)
            .where(SimulatedShipment.order_id == order_id)
        )
        attempts = session.scalars(
            select(IntegrationAttempt)
            .where(IntegrationAttempt.order_id == order_id,
                   IntegrationAttempt.integration == "shipping")
        ).all()
        state = session.get(Order, order_id).state
        assert sorted(results) == ["skipped", "skipped", "skipped", "succeeded"], results
        assert shipment_count == 1
        assert len(attempts) == 1 and attempts[0].outcome == "succeeded"
        assert state == OrderState.shipped
        print(json.dumps({
            "order_id": order_id,
            "concurrent_calls": 4,
            "results": sorted(results),
            "shipping_attempt_count": len(attempts),
            "shipment_count": shipment_count,
            "final_state": state.value,
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "stripe_api_called": False,
        }, indent=2))


if __name__ == "__main__":
    main()
