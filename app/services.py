from __future__ import annotations

from datetime import timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.integrations import IntegrationError, PaymentGateway, ShippingGateway
from app.models import IntegrationAttempt, Order, OrderState, ShippingJob, WebhookEvent, now


def locked_order(session: Session, order_id: str):
    return session.scalar(select(Order).where(Order.id == order_id).with_for_update())


def count_attempts(session: Session, order_id: str, integration: str) -> int:
    return len(session.scalars(select(IntegrationAttempt).where(
        IntegrationAttempt.order_id == order_id,
        IntegrationAttempt.integration == integration,
    )).all())


def start_payment(session: Session, order_id: str, gateway: PaymentGateway):
    order = locked_order(session, order_id)
    if order is None:
        return None, "not_found"
    if order.payment_intent_id or order.state not in (OrderState.awaiting_payment, OrderState.payment_pending):
        return order, "existing"
    if order.payment_started_at:
        started = order.payment_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if now() - started >= timedelta(hours=23):
            return order, "reconciliation_required"
    else:
        order.payment_started_at = now()
    order.state = OrderState.payment_pending
    sequence = count_attempts(session, order.id, "payment") + 1
    try:
        result = gateway.create_payment(order)
        order.payment_intent_id = result.intent_id
        outcome = "succeeded"
        error_code = None
        status = "created"
    except IntegrationError as exc:
        outcome = "temporary_failure" if exc.temporary else "permanent_failure"
        error_code = exc.code
        status = "retryable" if exc.temporary else "failed"
        if not exc.temporary:
            order.state = OrderState.payment_failed
    session.add(IntegrationAttempt(order_id=order.id, integration="payment", sequence=sequence,
                                   outcome=outcome, error_code=error_code))
    session.commit()
    return order, status


def process_webhook(session: Session, event: dict):
    event_id = event.get("id")
    event_type = event.get("type")
    if not isinstance(event_id, str) or not event_id.startswith("evt_"):
        return "invalid"
    if event_type not in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        return "ignored"
    obj = event.get("data", {}).get("object", {})
    order_id = obj.get("metadata", {}).get("order_id")
    intent_id = obj.get("id")
    if not isinstance(order_id, str) or not isinstance(intent_id, str):
        return "invalid"
    order = locked_order(session, order_id)
    if order is None:
        return "retry_later"
    if obj.get("amount") != order.amount or obj.get("currency") != order.currency:
        return "invalid"
    if order.payment_intent_id and order.payment_intent_id != intent_id:
        return "invalid"
    if not order.payment_intent_id and order.state != OrderState.payment_pending:
        return "retry_later"
    if session.get(WebhookEvent, event_id):
        return "duplicate"
    if not order.payment_intent_id:
        order.payment_intent_id = intent_id
    session.add(WebhookEvent(id=event_id, event_type=event_type, order_id=order.id))
    if event_type == "payment_intent.succeeded":
        if order.state in (OrderState.payment_pending, OrderState.payment_failed):
            order.state = OrderState.shipping_pending
            if session.get(ShippingJob, order.id) is None:
                session.add(ShippingJob(order_id=order.id, due_at=now()))
    elif order.state == OrderState.payment_pending:
        order.state = OrderState.payment_failed
    session.commit()
    return "processed"


def process_shipping(session: Session, order_id: str, gateway: ShippingGateway):
    order = locked_order(session, order_id)
    if order is None:
        return "not_found"
    job = session.get(ShippingJob, order_id)
    if job is None or job.done or order.state not in (OrderState.shipping_pending, OrderState.shipping_retrying):
        return "skipped"
    due_at = job.due_at.replace(tzinfo=timezone.utc) if job.due_at.tzinfo is None else job.due_at
    if due_at > now():
        return "not_due"
    sequence = job.attempts + 1
    retry_at = None
    try:
        order.shipment_id = gateway.create_shipment(session, order, f"shipment:{order.id}")
        order.state = OrderState.shipped
        job.done = True
        outcome = "succeeded"
        error_code = None
    except IntegrationError as exc:
        outcome = "temporary_failure" if exc.temporary else "permanent_failure"
        error_code = exc.code
        if exc.temporary and sequence < settings.shipping_max_attempts:
            retry_at = now() + timedelta(seconds=settings.shipping_retry_base_seconds * 2 ** (sequence - 1))
            job.due_at = retry_at
            order.state = OrderState.shipping_retrying
        else:
            job.done = True
            order.state = OrderState.shipping_failed
    job.attempts = sequence
    session.add(IntegrationAttempt(order_id=order.id, integration="shipping", sequence=sequence,
                                   outcome=outcome, error_code=error_code, next_retry_at=retry_at))
    session.commit()
    return outcome
