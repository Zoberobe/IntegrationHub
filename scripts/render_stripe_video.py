"""Render a silent portfolio video from the verified Stripe sandbox captures.

Install requirements-media.txt, then run: python -m scripts.render_stripe_video
"""

import json
import subprocess
from io import BytesIO
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "media"
SIZE = (1280, 720)
FPS = 12
NAVY = "#0a1730"
WHITE = "#f5f8ff"
MUTED = "#b6c5de"
VIOLET = "#8275ff"
GREEN = "#5ce0b8"
BORDER = "#253955"


def font(size, bold=False):
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    path = Path("C:/Windows/Fonts") / name
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default()


def base():
    image = Image.new("RGB", SIZE, NAVY)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 10, 720), fill=VIOLET)
    return image, draw


def title_slide():
    image, draw = base()
    draw.text((70, 105), "IntegrationHub", font=font(65, True), fill=WHITE)
    draw.rounded_rectangle((70, 210, 375, 262), radius=20, fill="#25234e")
    draw.text((91, 222), "STRIPE TEST MODE", font=font(22, True), fill="#c9c3ff")
    draw.text((70, 317), "Payment confirmed.", font=font(45, True), fill=WHITE)
    draw.text((70, 380), "Shipping fails once, then recovers.", font=font(39), fill=WHITE)
    draw.text((70, 500), "Signed webhook  /  persisted retry  /  one shipment", font=font(24), fill=MUTED)
    draw.line((70, 555, 980, 555), fill=BORDER, width=2)
    draw.text((70, 586), "Technical integration prototype  •  Local PostgreSQL, Redis, API and Celery", font=font(20), fill=MUTED)
    return image


def screenshot_slide(path, stage, heading):
    image, draw = base()
    draw.text((34, 24), stage, font=font(25, True), fill=VIOLET)
    draw.text((130, 24), heading, font=font(27, True), fill=WHITE)
    draw.text((1050, 29), "STRIPE SANDBOX", font=font(17, True), fill=MUTED)
    screenshot = Image.open(path).convert("RGB").crop((0, 0, 1440, 710))
    screenshot = screenshot.resize((1230, 606), Image.Resampling.LANCZOS)
    image.paste(screenshot, (25, 87))
    draw.rounded_rectangle((24, 86, 1256, 694), radius=5, outline=BORDER, width=2)
    return image


def evidence_slide(proof):
    image, draw = base()
    draw.text((70, 68), "Same Stripe event, delivered again", font=font(40, True), fill=WHITE)
    draw.text((70, 130), "Local signed replay of the Stripe-origin event", font=font(22), fill=MUTED)
    draw.rounded_rectangle((70, 200, 1210, 330), radius=20, fill="#17284a", outline=BORDER, width=2)
    draw.text((103, 225), "Webhook result", font=font(22), fill=MUTED)
    draw.text((103, 263), proof["replay_result"], font=font(38, True), fill=GREEN)
    draw.text((510, 243), proof["stripe_event_id"], font=font(22), fill=WHITE)
    for x, label, value in ((70, "Webhook events", proof["after"]["webhook_events"]),
                            (650, "Shipments", proof["after"]["shipments"])):
        draw.rounded_rectangle((x, 365, x + 560, 565), radius=20, fill="#17284a", outline=BORDER, width=2)
        draw.text((x + 35, 395), label, font=font(22), fill=MUTED)
        draw.text((x + 35, 442), str(value), font=font(75, True), fill=WHITE)
    draw.text((70, 618), "Final order state: shipped  •  First delivery: Stripe CLI  •  Payment mode: test", font=font(21), fill=MUTED)
    return image


def end_slide():
    image, draw = base()
    draw.text((70, 170), "Failure is visible.", font=font(54, True), fill=WHITE)
    draw.text((70, 250), "Recovery is automatic.", font=font(54, True), fill=WHITE)
    draw.text((70, 330), "Duplicate delivery creates no second shipment.", font=font(37), fill=GREEN)
    draw.line((70, 465, 1120, 465), fill=BORDER, width=2)
    draw.text((70, 510), "IntegrationHub  /  Stripe sandbox + PostgreSQL + Redis + Celery", font=font(23), fill=MUTED)
    return image


def jpeg_bytes(image):
    stream = BytesIO()
    image.save(stream, format="JPEG", quality=92, subsampling=0)
    return stream.getvalue()


def main():
    proof = json.loads((MEDIA / "stripe-sandbox-proof.json").read_text(encoding="utf-8"))
    if (proof["replay_result"] != "duplicate" or proof["after"] != {"webhook_events": 1, "shipments": 1}
            or proof["final_state"] != "shipped"):
        raise SystemExit("Stripe sandbox proof is incomplete")
    scenes = [
        (title_slide(), 3),
        (screenshot_slide(MEDIA / "stripe-retry.png", "01", "Temporary shipping failure"), 6),
        (screenshot_slide(MEDIA / "stripe-success.png", "02", "Second attempt succeeds"), 6),
        (evidence_slide(proof), 6),
        (end_slide(), 2),
    ]
    frames = b"".join(jpeg_bytes(image) * (seconds * FPS) for image, seconds in scenes)
    output = MEDIA / "stripe-sandbox-demo.mp4"
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "image2pipe", "-framerate", str(FPS), "-vcodec", "mjpeg", "-i", "pipe:0",
               "-c:v", "libx264", "-preset", "medium", "-crf", "22", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", str(output)]
    subprocess.run(command, input=frames, check=True)
    print(f"Created {output.name}: {sum(seconds for _, seconds in scenes)} seconds")


if __name__ == "__main__":
    main()
