import hashlib
import hmac
import json
import os
import time
from datetime import timedelta, timezone

import pytest
from fastapi.testclient import TestClient
import httpx
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ["DATABASE_URL"] = "sqlite://"

from app.db import Base
from app.db import get_db
from app.integrations import IntegrationError, PaymentResult, SimulatedShippingGateway, StripeGateway, verify_stripe_signature
from app.config import settings
from app.models import IntegrationAttempt, Order, OrderState, ShippingJob, SimulatedShipment, WebhookEvent, now
from app.services import process_shipping, process_webhook, start_payment
from app.main import app


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


class PaymentStub:
    def __init__(self):
        self.keys = []

    def create_payment(self, order):
        self.keys.append(order.payment_idempotency_key)
        if len(self.keys) == 1:
            raise IntegrationError("network_or_timeout", True)
        return PaymentResult("pi_test_1", "succeeded")


def test_timeout_reuses_payment_key_and_does_not_create_second_intent(session):
    order = Order(amount=2500, currency="brl", description="Test order")
    session.add(order)
    session.commit()
    gateway = PaymentStub()
    _, first = start_payment(session, order.id, gateway)
    _, second = start_payment(session, order.id, gateway)
    _, third = start_payment(session, order.id, gateway)
    assert (first, second, third) == ("retryable", "created", "existing")
    assert gateway.keys == [order.payment_idempotency_key] * 2
    assert len(session.scalars(select(IntegrationAttempt)).all()) == 2


def test_duplicate_webhook_and_failed_shipment_recover_with_one_shipment(session):
    order = Order(amount=2500, currency="brl", description="Demonstration",
                  state=OrderState.payment_pending, payment_intent_id="pi_test_1", shipping_fail_once=True)
    session.add(order)
    session.commit()
    event = {"id": "evt_test_1", "type": "payment_intent.succeeded",
             "data": {"object": {"id": "pi_test_1", "amount": 2500, "currency": "brl",
                                 "metadata": {"order_id": order.id}}}}
    assert process_webhook(session, event) == "processed"
    assert process_webhook(session, event) == "duplicate"
    assert session.scalar(select(WebhookEvent.id)) == "evt_test_1"
    assert session.get(Order, order.id).state == OrderState.shipping_pending

    gateway = SimulatedShippingGateway()
    assert process_shipping(session, order.id, gateway) == "temporary_failure"
    assert session.get(Order, order.id).state == OrderState.shipping_retrying
    job = session.get(ShippingJob, order.id)
    assert job.attempts == 1 and job.due_at.replace(tzinfo=timezone.utc) > now()
    job.due_at = now() - timedelta(seconds=1)
    session.commit()
    assert process_shipping(session, order.id, gateway) == "succeeded"
    shipment_id = session.get(Order, order.id).shipment_id
    assert process_shipping(session, order.id, gateway) == "skipped"
    assert session.get(Order, order.id).state == OrderState.shipped
    assert session.get(Order, order.id).shipment_id == shipment_id
    assert len(session.scalars(select(SimulatedShipment)).all()) == 1
    assert [(a.sequence, a.outcome) for a in session.scalars(select(IntegrationAttempt).order_by(IntegrationAttempt.sequence))] == [
        (1, "temporary_failure"), (2, "succeeded")]


def test_webhook_signature_rejects_tampering_and_expiry():
    payload = json.dumps({"id": "evt_test"}).encode()
    timestamp = int(time.time())
    digest = hmac.new(b"whsec_test", str(timestamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
    header = f"t={timestamp},v1={digest}"
    assert verify_stripe_signature(payload, header, "whsec_test") == {"id": "evt_test"}
    with pytest.raises(ValueError):
        verify_stripe_signature(payload + b" ", header, "whsec_test")
    with pytest.raises(ValueError):
        verify_stripe_signature(payload, header, "whsec_test", current_time=timestamp + 301)


def test_mismatched_payment_intent_never_ships(session):
    order = Order(amount=2500, currency="brl", description="Test order",
                  state=OrderState.payment_pending, payment_intent_id="pi_expected")
    session.add(order)
    session.commit()
    event = {"id": "evt_wrong", "type": "payment_intent.succeeded",
             "data": {"object": {"id": "pi_other", "amount": 2500, "currency": "brl",
                                 "metadata": {"order_id": order.id}}}}
    assert process_webhook(session, event) == "invalid"
    assert session.get(Order, order.id).state == OrderState.payment_pending
    assert session.get(ShippingJob, order.id) is None


def test_http_api_and_dashboard_hide_secrets(session):
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            created = client.post("/orders", json={"amount": 2500, "description": "Visual order"})
            assert created.status_code == 201
            order_id = created.json()["id"]
            assert client.get(f"/orders/{order_id}").json()["state"] == "awaiting_payment"
            assert client.get("/docs").status_code == 200
            dashboard = client.get("/dashboard")
            assert dashboard.status_code == 200 and "Visual order" in dashboard.text
            assert "payment_idempotency_key" not in dashboard.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("test_key", ["sk_test_example", "rk_test_example"])
def test_stripe_sandbox_request_uses_stable_key_and_timeout(monkeypatch, test_key):
    order = Order(id="order-test", amount=2500, currency="brl", description="Test order",
                  payment_idempotency_key="idem-test")
    monkeypatch.setattr(settings, "stripe_secret_key", test_key)
    observed = {}

    def fake_post(url, **kwargs):
        observed.update({"url": url, **kwargs})
        return httpx.Response(200, json={"id": "pi_test_1", "status": "succeeded"})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = StripeGateway().create_payment(order)
    assert result.intent_id == "pi_test_1"
    assert observed["headers"]["Idempotency-Key"] == "idem-test"
    assert observed["data"]["metadata[order_id]"] == "order-test"
    assert "payment_method_types[]" not in observed["data"]
    assert observed["data"]["allowed_payment_method_types[]"] == "card"
    assert observed["auth"][0] == test_key
    assert observed["timeout"] == settings.payment_timeout_seconds


def test_webhook_http_signature_and_duplicate(session, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test")
    order = Order(amount=2500, currency="brl", description="Test order",
                  state=OrderState.payment_pending, payment_intent_id="pi_test_1")
    session.add(order)
    session.commit()
    payload = json.dumps({"id": "evt_http", "type": "payment_intent.succeeded",
                          "data": {"object": {"id": "pi_test_1", "amount": 2500,
                                              "currency": "brl", "metadata": {"order_id": order.id}}}}).encode()
    timestamp = int(time.time())
    digest = hmac.new(b"whsec_test", str(timestamp).encode() + b"." + payload, hashlib.sha256).hexdigest()
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as client:
            bad = client.post("/webhooks/stripe", content=payload, headers={"stripe-signature": "bad"})
            assert bad.status_code == 400
            headers = {"stripe-signature": f"t={timestamp},v1={digest}"}
            assert client.post("/webhooks/stripe", content=payload, headers=headers).json()["result"] == "processed"
            assert client.post("/webhooks/stripe", content=payload, headers=headers).json()["result"] == "duplicate"
            assert client.get(f"/orders/{order.id}").json()["state"] == "shipping_pending"
    finally:
        app.dependency_overrides.clear()


def test_shipping_stops_after_temporary_retry_limit(session):
    class AlwaysUnavailable:
        def create_shipment(self, session, order, key):
            raise IntegrationError("simulated_503", True)

    order = Order(amount=2500, currency="brl", description="Retry limit",
                  state=OrderState.shipping_pending)
    session.add(order)
    session.commit()
    session.add(ShippingJob(order_id=order.id, due_at=now()))
    session.commit()
    for attempt in range(3):
        assert process_shipping(session, order.id, AlwaysUnavailable()) == "temporary_failure"
        if attempt < 2:
            job = session.get(ShippingJob, order.id)
            job.due_at = now() - timedelta(seconds=1)
            session.commit()
    assert session.get(Order, order.id).state == OrderState.shipping_failed
    assert process_shipping(session, order.id, AlwaysUnavailable()) == "skipped"
    assert session.get(ShippingJob, order.id).attempts == 3
