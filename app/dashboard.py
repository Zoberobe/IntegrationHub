"""Operational view of one order's payment and shipping evidence."""

from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import IntegrationAttempt, Order, ShippingJob, SimulatedShipment, WebhookEvent


def _text(value):
    return escape(str(value))


def dashboard_html(session: Session) -> str:
    orders = session.scalars(select(Order).order_by(Order.created_at.desc()).limit(100)).all()
    latest = orders[0] if orders else None
    retrying = sum(order.state.value == "shipping_retrying" for order in orders)
    shipped = sum(order.state.value == "shipped" for order in orders)

    if latest:
        attempts = session.scalars(
            select(IntegrationAttempt)
            .where(IntegrationAttempt.order_id == latest.id)
            .order_by(IntegrationAttempt.created_at, IntegrationAttempt.sequence)
        ).all()
        shipping_attempts = [attempt for attempt in attempts if attempt.integration == "shipping"]
        first_failure = next((attempt for attempt in shipping_attempts if attempt.error_code), None)
        shipment_count = session.scalar(
            select(func.count()).select_from(SimulatedShipment)
            .where(SimulatedShipment.order_id == latest.id)
        )
        webhook_count = session.scalar(
            select(func.count()).select_from(WebhookEvent)
            .where(WebhookEvent.order_id == latest.id)
        )
        job = session.get(ShippingJob, latest.id)
        if latest.payment_intent_id and latest.payment_intent_id.startswith("pi_offline_"):
            source = "Offline preview"
        elif latest.payment_intent_id and latest.payment_intent_id.startswith("pi_local_"):
            source = "Local full-stack proof"
        else:
            source = "Stripe test-mode flow"
        retry_time = job.due_at.strftime("%Y-%m-%d %H:%M UTC") if job and not job.done else None
        recovery = (
            "Recovery complete: one shipment after a temporary failure."
            if latest.state.value == "shipped" and first_failure and shipment_count == 1
            else "The order remains traceable while the next attempt is pending."
            if latest.state.value == "shipping_retrying"
            else "Follow the order through payment, webhook, and shipping."
        )
        attempt_rows = "".join(
            "<li><span>Attempt " + _text(attempt.sequence) + "</span>"
            + "<b>" + _text(attempt.outcome.replace("_", " ")) + "</b>"
            + "<code>" + _text(attempt.error_code or "no error") + "</code></li>"
            for attempt in shipping_attempts
        ) or "<li>No shipping attempts yet</li>"
        focus = (
            "<section class='focus'>"
            "<div class='focus-head'><div><p class='eyebrow'>LATEST ORDER · " + _text(source) + "</p>"
            "<h2>" + _text(latest.description) + "</h2>"
            "<p class='order-id'>Order " + _text(latest.id) + "</p></div>"
            "<span class='badge'>" + _text(latest.state.value) + "</span></div>"
            "<div class='journey'>"
            "<div class='step'><span class='step-index'>01</span><h3>Payment signal</h3>"
            "<strong>" + ("Recorded" if webhook_count else "Waiting") + "</strong>"
            "<p>" + _text(webhook_count) + " webhook event stored</p></div>"
            "<div class='step'><span class='step-index'>02</span><h3>Shipping failure</h3>"
            "<strong>" + (_text(first_failure.error_code) if first_failure else "Waiting") + "</strong>"
            "<p>" + _text(len(shipping_attempts)) + " shipping attempt(s)</p></div>"
            "<div class='step'><span class='step-index'>03</span><h3>Shipment</h3>"
            "<strong>" + _text(shipment_count) + " created</strong>"
            "<p>" + (_text(retry_time) + " next retry" if retry_time else "No retry pending") + "</p></div>"
            "</div><div class='evidence'><div><h3>Evidence</h3><p>" + _text(recovery) + "</p>"
            "<p class='muted'>Payment intent: " + _text(latest.payment_intent_id or "pending") + "</p></div>"
            "<ol>" + attempt_rows + "</ol></div></section>"
        )
    else:
        focus = "<section class='focus empty'><h2>No orders yet</h2><p>Create an order through the API to start the flow.</p></section>"

    action_labels = {
        "awaiting_payment": "Start payment",
        "payment_pending": "Wait for webhook",
        "payment_failed": "Manual review",
        "shipping_pending": "Wait for worker",
        "shipping_retrying": "Wait for retry",
        "shipping_failed": "Manual review",
        "shipped": "Complete",
        "paid": "Wait for shipping",
    }
    rows = []
    for order in orders:
        shipping_attempts = session.scalars(
            select(IntegrationAttempt).where(
                IntegrationAttempt.order_id == order.id,
                IntegrationAttempt.integration == "shipping",
            ).order_by(IntegrationAttempt.sequence)
        ).all()
        count = session.scalar(
            select(func.count()).select_from(SimulatedShipment)
            .where(SimulatedShipment.order_id == order.id)
        )
        failures = ", ".join(
            f"#{attempt.sequence}: {attempt.error_code}"
            for attempt in shipping_attempts if attempt.error_code
        ) or "—"
        rows.append(
            "<tr><td class='mono' title='" + _text(order.id) + "'>" + _text(order.id[:8]) + "…</td>"
            "<td>" + _text(order.description) + "</td>"
            "<td><span class='badge'>" + _text(order.state.value) + "</span></td>"
            "<td>" + _text(len(shipping_attempts)) + "</td>"
            "<td>" + _text(count) + "</td>"
            "<td>" + _text(failures) + "</td>"
            "<td>" + _text(action_labels[order.state.value]) + "</td></tr>"
        )

    return """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="5"><title>IntegrationHub · Operations</title><style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#18304b;background:#f4f7fb}
body{margin:0}main{max-width:1300px;margin:auto;padding:34px 28px 70px}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px}
h1{font-size:30px;letter-spacing:-.04em;margin:0}h2{font-size:25px;margin:5px 0 8px}h3{font-size:15px;margin:8px 0}
p{margin:7px 0}a{color:#2359a3;text-decoration:none;font-weight:650}
.muted,.sub,.order-id{color:#64758b}.sub{margin-top:4px}.eyebrow{color:#547096;font-weight:750;letter-spacing:.12em;font-size:11px}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:19px}
.metric,.focus,.tablewrap{background:white;border:1px solid #e2e9f2;border-radius:15px;box-shadow:0 7px 20px #233c5a0a}
.metric{padding:17px 23px}.metric b{display:block;font-size:27px}.metric span{color:#64758b;font-size:13px}
.focus{padding:27px;margin-bottom:22px}.focus-head{display:flex;justify-content:space-between;gap:20px;align-items:start}
.badge{background:#eaf2ff;color:#235b9e;border-radius:999px;padding:5px 10px;font:12px ui-monospace,Consolas,monospace;white-space:nowrap}
.order-id{font:12px ui-monospace,Consolas,monospace}
.journey{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:23px}
.step{background:#f7faff;border:1px solid #e1eaf5;border-radius:12px;padding:18px;min-height:112px}
.step-index{font-size:11px;color:#6d85a3;font-weight:800}.step strong{display:block;font-size:20px;margin:9px 0}
.step p{font-size:13px;color:#64758b}
.evidence{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:18px;background:#edf5ff;border-radius:12px;padding:14px 18px}
.evidence ol{list-style:none;margin:0;padding:0}.evidence li{display:flex;gap:12px;padding:6px 0;border-bottom:1px solid #d9e5f5;font-size:13px}
.evidence li:last-child{border:0}.evidence li span{min-width:70px;color:#64758b}.evidence code{margin-left:auto}
.tablewrap{overflow:auto}.tablewrap h3{margin:17px 20px}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{text-align:left;padding:14px 17px;border-top:1px solid #edf1f6;vertical-align:top}
th{color:#6a7c94;background:#fafcff;text-transform:uppercase;letter-spacing:.07em;font-size:11px}
.mono{font:12px ui-monospace,Consolas,monospace;white-space:nowrap}.empty{min-height:130px}
@media(max-width:800px){.metrics,.journey,.evidence{grid-template-columns:1fr}header{align-items:start;gap:20px}}
</style><main><header><div><h1>IntegrationHub</h1><p class="sub">Operational proof for payments, webhooks, and shipping</p></div>
<a href="/docs">API documentation ↗</a></header><div class="metrics">
<div class="metric"><b>""" + str(len(orders)) + """</b><span>Orders</span></div>
<div class="metric"><b>""" + str(retrying) + """</b><span>Awaiting retry</span></div>
<div class="metric"><b>""" + str(shipped) + """</b><span>Shipped</span></div></div>""" + focus + """
<section class="tablewrap"><h3>All orders</h3><table><thead><tr><th>Order</th><th>Description</th><th>Status</th>
<th>Shipping attempts</th><th>Shipments</th><th>Failures</th><th>Next action</th></tr></thead><tbody>""" + "".join(rows) + """</tbody></table></section></main></html>"""
