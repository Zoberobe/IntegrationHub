from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, SimulatedShipment


class IntegrationError(Exception):
    def __init__(self, code: str, temporary: bool):
        super().__init__(code)
        self.code = code
        self.temporary = temporary


@dataclass
class PaymentResult:
    intent_id: str
    status: str


class PaymentGateway(Protocol):
    def create_payment(self, order: Order) -> PaymentResult: ...


class ShippingGateway(Protocol):
    def create_shipment(self, session: Session, order: Order, key: str) -> str: ...


class StripeGateway:
    def create_payment(self, order: Order) -> PaymentResult:
        if not settings.stripe_secret_key.startswith(("sk_test_", "rk_test_")):
            raise IntegrationError("sandbox_key_missing", False)
        try:
            response = httpx.post(
                f"{settings.stripe_api_base}/v1/payment_intents",
                auth=(settings.stripe_secret_key, ""),
                headers={"Idempotency-Key": order.payment_idempotency_key},
                data={
                    "amount": order.amount,
                    "currency": order.currency,
                    "description": order.description,
                    "payment_method": "pm_card_visa",
                    "allowed_payment_method_types[]": "card",
                    "confirm": "true",
                    "metadata[order_id]": order.id,
                },
                timeout=settings.payment_timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            raise IntegrationError("network_or_timeout", True)
        if response.status_code >= 500 or response.status_code == 429:
            raise IntegrationError("provider_unavailable", True)
        if response.status_code >= 400:
            raise IntegrationError("provider_rejected", False)
        try:
            body = response.json()
            return PaymentResult(body["id"], body["status"])
        except (ValueError, KeyError, TypeError):
            raise IntegrationError("invalid_provider_response", True)


class SimulatedShippingGateway:
    """Persistent idempotency plus an optional fail-before-create demo scenario."""

    def create_shipment(self, session: Session, order: Order, key: str) -> str:
        existing = session.get(SimulatedShipment, key)
        if existing:
            return existing.shipment_id
        if order.shipping_fail_once and not order.shipping_failure_used:
            order.shipping_failure_used = True
            raise IntegrationError("simulated_503", True)
        shipment = SimulatedShipment(idempotency_key=key, order_id=order.id)
        session.add(shipment)
        session.flush()
        return shipment.shipment_id


def verify_stripe_signature(payload: bytes, signature: str, secret: str, current_time: int | None = None) -> dict:
    if not secret:
        raise ValueError("webhook secret missing")
    values = {}
    for item in signature.split(","):
        key, sep, value = item.partition("=")
        if sep:
            values.setdefault(key, []).append(value)
    try:
        timestamp = int(values["t"][0])
        signatures = values["v1"]
    except (KeyError, IndexError, ValueError):
        raise ValueError("invalid signature header")
    if abs((current_time or int(time.time())) - timestamp) > 300:
        raise ValueError("signature expired")
    signed = str(timestamp).encode() + b"." + payload
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise ValueError("invalid signature")
    try:
        return json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("invalid payload")
