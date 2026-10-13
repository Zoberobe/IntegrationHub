"""Create deterministic local visuals without Stripe credentials.

This is a preview of the operational flow. The real sandbox path uses /orders/{id}/payment.
"""

import sys
from datetime import timedelta

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.integrations import SimulatedShippingGateway
from app.models import Order, OrderState, ShippingJob, SimulatedShipment, now
from app.services import process_shipping, process_webhook


def main(stage):
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if stage == "start":
            order = Order(amount=2500, currency="brl", description="Failure and recovery demo",
                          state=OrderState.payment_pending,
                          shipping_fail_once=True)
            session.add(order)
            session.flush()
            order.payment_intent_id = "pi_offline_" + order.id
            session.commit()
            event = {"id": "evt_offline_" + order.id, "type": "payment_intent.succeeded",
                     "data": {"object": {"id": order.payment_intent_id, "amount": order.amount,
                                         "currency": order.currency, "metadata": {"order_id": order.id}}}}
            assert process_webhook(session, event) == "processed"
            assert process_webhook(session, event) == "duplicate"
            assert process_shipping(session, order.id, SimulatedShippingGateway()) == "temporary_failure"
            print(order.id)
        elif stage == "finish":
            order = session.scalar(select(Order).where(Order.description == "Failure and recovery demo")
                                   .order_by(Order.created_at.desc()))
            if order is None:
                raise SystemExit("Run start first")
            job = session.get(ShippingJob, order.id)
            job.due_at = now() - timedelta(seconds=1)
            session.commit()
            assert process_shipping(session, order.id, SimulatedShippingGateway()) == "succeeded"
            assert process_shipping(session, order.id, SimulatedShippingGateway()) == "skipped"
            count = len(session.scalars(select(SimulatedShipment).where(SimulatedShipment.order_id == order.id)).all())
            assert count == 1
            print(f"{order.id}: {count} shipment")
        else:
            raise SystemExit("Usage: python -m scripts.demo_offline start|finish")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "")
