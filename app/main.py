from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
import swagger_ui_bundle

from app.config import settings
from app.db import Base, engine, get_db
from app.integrations import StripeGateway, verify_stripe_signature
from app.models import IntegrationAttempt, Order, ShippingJob, SimulatedShipment, WebhookEvent
from app.services import process_webhook, start_payment
from app.dashboard import dashboard_html


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="IntegrationHub", description="Orders, Stripe sandbox payments, and asynchronous shipping",
              lifespan=lifespan, docs_url=None)
app.openapi_version = "3.0.3"
swagger_assets = next((Path(swagger_ui_bundle.__file__).parent / "vendor").glob("swagger-ui-*"))
app.mount("/swagger-static", StaticFiles(directory=swagger_assets), name="swagger-static")


@app.get("/docs", include_in_schema=False)
def docs():
    return get_swagger_ui_html(openapi_url=app.openapi_url, title="IntegrationHub API",
                               swagger_js_url="/swagger-static/swagger-ui-bundle.js",
                               swagger_css_url="/swagger-static/swagger-ui.css")


class OrderCreate(BaseModel):
    amount: int = Field(ge=50, le=99999999, description="Amount in minor currency units")
    currency: str = Field(default="brl", pattern="^[a-z]{3}$")
    description: str = Field(min_length=1, max_length=200)
    shipping_fail_once: bool = False


def order_view(order: Order, session: Session):
    attempts = session.scalars(select(IntegrationAttempt).where(IntegrationAttempt.order_id == order.id)
                               .order_by(IntegrationAttempt.created_at, IntegrationAttempt.sequence)).all()
    job = session.get(ShippingJob, order.id)
    return {
        "id": order.id, "amount": order.amount, "currency": order.currency,
        "description": order.description, "state": order.state.value,
        "payment_intent_id": order.payment_intent_id, "shipment_id": order.shipment_id,
        "next_action": {
            "awaiting_payment": "start_payment", "payment_pending": "wait_for_webhook_or_retry_payment",
            "payment_failed": "manual_review", "shipping_pending": "wait_for_worker",
            "shipping_retrying": "wait_for_retry", "shipping_failed": "manual_review",
            "shipped": "complete", "paid": "wait_for_shipping",
        }[order.state.value],
        "shipping_next_retry_at": job.due_at.isoformat() if job and not job.done else None,
        "attempts": [{"integration": x.integration, "sequence": x.sequence, "outcome": x.outcome,
                      "error_code": x.error_code,
                      "next_retry_at": x.next_retry_at.isoformat() if x.next_retry_at else None}
                     for x in attempts],
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/orders", status_code=201)
def create_order(body: OrderCreate, session: Session = Depends(get_db)):
    order = Order(**body.model_dump())
    session.add(order)
    session.commit()
    return order_view(order, session)


@app.get("/orders")
def list_orders(session: Session = Depends(get_db)):
    orders = session.scalars(select(Order).order_by(Order.created_at.desc()).limit(100)).all()
    return [order_view(order, session) for order in orders]


@app.get("/orders/{order_id}")
def get_order(order_id: str, session: Session = Depends(get_db)):
    order = session.get(Order, order_id)
    if not order:
        raise HTTPException(404, "order not found")
    return order_view(order, session)


@app.post("/orders/{order_id}/payment")
def pay(order_id: str, session: Session = Depends(get_db)):
    order, result = start_payment(session, order_id, StripeGateway())
    if order is None:
        raise HTTPException(404, "order not found")
    if result == "reconciliation_required":
        raise HTTPException(409, "payment outcome uncertain; reconcile with Stripe")
    return {"result": result, "order": order_view(order, session)}


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default=""),
                         session: Session = Depends(get_db)):
    payload = await request.body()
    try:
        event = verify_stripe_signature(payload, stripe_signature, settings.stripe_webhook_secret)
    except ValueError:
        raise HTTPException(400, "invalid webhook signature or payload")
    result = process_webhook(session, event)
    if result == "invalid":
        raise HTTPException(400, "invalid webhook event")
    if result == "retry_later":
        raise HTTPException(503, "order not ready; retry webhook")
    return {"result": result}


@app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(session: Session = Depends(get_db)):
    return dashboard_html(session)
