from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid.uuid4())


class OrderState(str, enum.Enum):
    awaiting_payment = "awaiting_payment"
    payment_pending = "payment_pending"
    paid = "paid"
    shipping_pending = "shipping_pending"
    shipping_retrying = "shipping_retrying"
    shipped = "shipped"
    shipping_failed = "shipping_failed"
    payment_failed = "payment_failed"


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="brl")
    description: Mapped[str] = mapped_column(String(200))
    state: Mapped[OrderState] = mapped_column(Enum(OrderState), default=OrderState.awaiting_payment)
    payment_intent_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    payment_idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, default=uid)
    payment_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    shipping_fail_once: Mapped[bool] = mapped_column(Boolean, default=False)
    shipping_failure_used: Mapped[bool] = mapped_column(Boolean, default=False)
    shipment_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    attempts: Mapped[list["IntegrationAttempt"]] = relationship(back_populates="order", order_by="IntegrationAttempt.created_at")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IntegrationAttempt(Base):
    __tablename__ = "integration_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    integration: Mapped[str] = mapped_column(String(20))
    sequence: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[Optional[str]] = mapped_column(String(60))
    next_retry_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    order: Mapped[Order] = relationship(back_populates="attempts")
    __table_args__ = (UniqueConstraint("order_id", "integration", "sequence"),)


class ShippingJob(Base):
    __tablename__ = "shipping_jobs"
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), primary_key=True)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[bool] = mapped_column(Boolean, default=False)


class SimulatedShipment(Base):
    __tablename__ = "simulated_shipments"
    idempotency_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    shipment_id: Mapped[str] = mapped_column(String(100), unique=True, default=uid)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), unique=True)
