"""Run the Stripe test-mode webhook listener without printing its secret.

The active listener's signing secret is written to the ignored local .env file.
Keep this process running while testing payments.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
SECRET_PATTERN = re.compile(r"whsec_[A-Za-z0-9]+")


def save_secret(secret):
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith("STRIPE_WEBHOOK_SECRET="):
            lines[index] = "STRIPE_WEBHOOK_SECRET=" + secret
            replaced = True
            break
    if not replaced:
        lines.append("STRIPE_WEBHOOK_SECRET=" + secret)
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    cli = shutil.which("stripe.cmd") or shutil.which("stripe")
    if not cli:
        raise SystemExit("Stripe CLI is not installed")
    command = [cli, "listen", "--events", "payment_intent.succeeded,payment_intent.payment_failed",
               "--forward-to", "localhost:54321/webhooks/stripe", "--color", "off", "--skip-update"]
    process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, bufsize=1)
    ready = False
    try:
        for line in process.stdout:
            match = SECRET_PATTERN.search(line)
            if match and not ready:
                save_secret(match.group(0))
                ready = True
                print("STRIPE_LISTENER_READY; webhook secret saved to local .env", flush=True)
                continue
            if "payment_intent.succeeded" in line:
                print("STRIPE_EVENT payment_intent.succeeded", flush=True)
            elif "payment_intent.payment_failed" in line:
                print("STRIPE_EVENT payment_intent.payment_failed", flush=True)
            else:
                status = re.search(r"\[(\d{3})\]", line)
                if status:
                    print("STRIPE_FORWARD_HTTP_" + status.group(1), flush=True)
        if not ready:
            raise SystemExit("Stripe listener exited before providing its signing secret")
        raise SystemExit(process.wait())
    except KeyboardInterrupt:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
