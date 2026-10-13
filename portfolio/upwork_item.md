# IntegrationHub — Upwork portfolio item

Use this as a portfolio item on a freelancer profile. IntegrationHub is a self-directed technical case study, not client work. The public page is an interactive simulation; the video shows a separate Stripe test-mode validation recorded on October 9, 2026.

## Copy-ready fields

**Title**

IntegrationHub | Reliable Stripe Payment and Shipping Workflow

**Role**

Python Backend Developer | API Integrations

**Project description**

**Problem:** A successful payment can be followed by a failed shipping request or a repeated webhook. Without reliable state tracking, an order may be lost or shipped twice.

**Solution:** I built a FastAPI workflow with Stripe test-mode payments, verified and deduplicated webhooks, a persistent PostgreSQL shipping job, Celery retries, and an operations dashboard. A stable payment key and a unique shipment record protect repeated requests.

**Result:** In the recorded sandbox run, shipping failed temporarily, recovered on the second attempt, and created exactly one shipment. Replaying the same signed event did not create another. The repository includes nine passing automated domain and API tests, saved PostgreSQL/Redis/Celery evidence, and a public interactive preview.

Shipping is simulated in this case study. The public preview runs in the browser and does not make Stripe or backend calls.

**Skills and deliverables — choose available tags**

- Python
- FastAPI
- Stripe
- PostgreSQL
- Celery

## Media to upload, in order

1. [Stripe test-mode walkthrough](../media/stripe-sandbox-demo.mp4) — lead with this 23-second video. It shows payment confirmation, signed webhook, temporary shipping failure, recovery, and the one-shipment result.
2. [Successful result](../media/stripe-success.png) — cover or supporting image from the same recorded run.
3. [Temporary failure](../media/stripe-retry.png) — the order remains visible while a retry is scheduled.
4. [Full-stack dashboard](../media/fullstack-dashboard.png) — local PostgreSQL/Redis/Celery proof using a locally seeded payment intent; label it separately from the Stripe run.

## External links

- Interactive preview: https://zoberobe.github.io/IntegrationHub/
- Source, tests, and saved evidence: https://github.com/Zoberobe/IntegrationHub
- Direct video: https://github.com/Zoberobe/IntegrationHub/blob/main/media/stripe-sandbox-demo.mp4

The saved [payment audit](../media/stripe-rotated-key-audit.json) and [same-event replay proof](../media/stripe-rotated-key-replay.json) support the Stripe result. The [full-stack proof](../media/fullstack-proof.json) and [concurrency proof](../media/concurrency-proof.json) document the local infrastructure run. These infrastructure and Stripe checks were recorded on October 9, 2026; the automated SQLite suite runs in CI on new changes.

## Posting

Create a portfolio item on the Upwork freelancer profile, paste the fields above, upload the video first, add the supporting images and links, review the preview, and publish. Leave related client jobs empty because this is a self-directed case study.
