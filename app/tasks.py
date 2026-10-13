from celery import Celery
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.integrations import SimulatedShippingGateway
from app.models import ShippingJob, now
from app.services import process_shipping


celery_app = Celery("integrationhub", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.beat_schedule = {
    "dispatch-due-shipments": {"task": "app.tasks.dispatch_due_shipments", "schedule": 5.0}
}
celery_app.conf.task_serializer = "json"
celery_app.conf.accept_content = ["json"]


@celery_app.task(name="app.tasks.dispatch_due_shipments")
def dispatch_due_shipments():
    with SessionLocal() as session:
        due_ids = session.scalars(select(ShippingJob.order_id).where(
            ShippingJob.done.is_(False), ShippingJob.due_at <= now()
        ).limit(100)).all()
    for order_id in due_ids:
        ship_order.delay(order_id)
    return len(due_ids)


@celery_app.task(name="app.tasks.ship_order")
def ship_order(order_id: str):
    with SessionLocal() as session:
        return process_shipping(session, order_id, SimulatedShippingGateway())
