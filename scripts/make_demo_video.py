"""Combine the three captured screens into a 15-second silent WebM preview."""

import os
import subprocess
from io import BytesIO
from pathlib import Path

from PIL import Image


root = Path(__file__).resolve().parents[1]
screens = [root / "media" / name for name in ("api.png", "retry.png", "success.png")]
frames = b""
for path in screens:
    frame = BytesIO()
    Image.open(path).convert("RGB").save(frame, format="JPEG", quality=95)
    frames += frame.getvalue() * 60
command = [os.getenv("FFMPEG_EXE", "ffmpeg"), "-hide_banner", "-y", "-f", "image2pipe",
           "-framerate", "12", "-vcodec", "mjpeg", "-i", "pipe:0", "-c:v", "libvpx",
           "-b:v", "900k", "-pix_fmt", "yuv420p", "-f", "webm", str(root / "media" / "demo.webm")]
subprocess.run(command, input=frames, check=True, stdout=subprocess.DEVNULL)
