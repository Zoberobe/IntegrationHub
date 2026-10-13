# Validation runbooks

IntegrationHub is a technical integration prototype. These paths separate the offline preview, the PostgreSQL/Redis/Celery proof, and the real Stripe sandbox check. Label each piece of evidence with its path.

## A. Offline preview (a few minutes)

This path uses SQLite and a locally generated payment event. It does not contact Stripe or run Celery.

1. Install dependencies:

    python -m venv .venv
    .\.venv\Scripts\python -m pip install -r requirements.txt

2. In the API terminal, set DATABASE_URL to sqlite:///./preview.db and start the API:

    $env:DATABASE_URL='sqlite:///./preview.db'
    .\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 54321

3. In a second terminal, set the same DATABASE_URL and create the failure state:

    $env:DATABASE_URL='sqlite:///./preview.db'
    .\.venv\Scripts\python -m scripts.demo_offline start

4. Capture http://localhost:54321/dashboard while the order shows shipping_retrying, attempt 1, and simulated_503.
5. In the second terminal, run the following and refresh the dashboard:

    .\.venv\Scripts\python -m scripts.demo_offline finish

The order should show shipped, two shipping attempts, and one shipment. The supplied media files are from this offline path.

## B. Full-stack local proof (PostgreSQL, Redis, Celery)

This path verifies the signed webhook endpoint, persistent job, worker retry, database row locking, and the single-shipment invariant. It seeds a local payment intent because it does not make a Stripe API call.

1. Copy .env.example to .env. The placeholder STRIPE_WEBHOOK_SECRET is sufficient for this local proof. Start the stack:

    docker compose up --build -d
    docker compose ps

2. Run the proof script inside the API container:

    docker compose exec api python -m scripts.fullstack_proof

3. Save the JSON output. It must show webhook results processed and duplicate, shipping outcomes temporary_failure and succeeded, shipment_count of 1, webhook_event_count of 1, and final state shipped. The script also dispatches duplicate shipping tasks after completion.

4. Query PostgreSQL for the same order ID:

    docker compose exec db psql -U integrationhub -d integrationhub -c 'select order_id, count(*) from simulated_shipments group by order_id;'
    docker compose exec db psql -U integrationhub -d integrationhub -c 'select order_id, integration, sequence, outcome, error_code from integration_attempts order by created_at;'

To verify PostgreSQL row locking under four simultaneous shipping calls, pause Beat briefly and run the focused proof:

    docker compose stop beat
    docker compose exec api python -m scripts.concurrency_proof
    docker compose start beat

The expected result is one `succeeded`, three `skipped`, one shipping attempt, and one shipment. The saved examples are [fullstack-proof.json](media/fullstack-proof.json), [concurrency-proof.json](media/concurrency-proof.json), and [fullstack-dashboard.png](media/fullstack-dashboard.png). They use a locally seeded payment intent and are not Stripe API evidence.

If the script fails, inspect docker compose logs --tail=100 api worker beat db redis. Do not include secrets in shared logs or screenshots.

## C. Real Stripe test-mode flow

This path adds the external sandbox call to the full stack.

1. Replace STRIPE_SECRET_KEY in .env with a real sk_test_ or rk_test_ key (the restricted key needs Payment Intents write/read and Events read permissions). Run stripe listen --forward-to localhost:54321/webhooks/stripe and put its whsec_ secret in .env. Restart API, worker, and Beat after changing environment variables.
2. Create an order with shipping_fail_once=true and call POST /orders/{id}/payment as shown in the README. Keep the order ID and PaymentIntent ID.
3. Confirm the payment_intent.succeeded event was received, then wait for the first shipping failure and second successful attempt.
4. After the order reaches shipped, run `docker compose exec api python -m scripts.stripe_replay ORDER_ID`. This fetches the Stripe-origin event by its stored ID, signs a local replay with the active CLI listener secret, and requires a duplicate result with counts unchanged. A newly generated event is not a duplicate test.
5. Run `docker compose exec api python -m scripts.stripe_payment_audit ORDER_ID` to retrieve the PaymentIntent from Stripe and verify status succeeded, livemode false, the two shipping attempts, and a single shipment. Capture the dashboard during shipping_retrying and after shipped; label them as the real sandbox run only after they are observed.

A second 2026-10-09 run using a rotated restricted test key (`rk_test_`) is saved as [payment audit](media/stripe-rotated-key-audit.json) and [same-event replay](media/stripe-rotated-key-replay.json). It confirms the same one-shipment invariant after a real Stripe test-mode payment and signed CLI-forwarded webhook.

The verified 2026-10-09 run is saved as [payment audit](media/stripe-payment-audit.json), [same-event replay](media/stripe-sandbox-proof.json), [retry capture](media/stripe-retry.png), [success capture](media/stripe-success.png), and [23-second video](media/stripe-sandbox-demo.mp4). The Stripe CLI delivered the first webhook; the replay was locally signed using the CLI listener secret.

Do not paste Stripe keys or webhook secrets into tickets, logs, screenshots, or portfolio material.

## Acceptance criteria

- PostgreSQL, Redis, API, worker, and Beat are running.
- The full-stack proof shows one temporary shipping failure, one successful retry, and exactly one shipment.
- A repeated signed webhook is recognized as a duplicate and does not create another shipment.
- The real Stripe test-mode payment and webhook are observed separately.
- The portfolio screenshots and video state which path produced them.
