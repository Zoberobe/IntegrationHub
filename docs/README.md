# Public interactive demo

GitHub Pages serves this directory at `https://zoberobe.github.io/IntegrationHub/`.

The controls run a deterministic, browser-only simulation of IntegrationHub's order state transitions. They do not call Stripe, the API, Redis, or PostgreSQL. The embedded video and linked JSON files document a separate real Stripe test-mode run. The backend source and reproducible validation steps are in the parent project.

Open `index.html` through a static HTTP server for local preview.
