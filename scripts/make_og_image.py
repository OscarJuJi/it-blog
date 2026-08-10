"""Render static/og.png, the card shown when a link to the blog is shared.

Run by hand, not by the build -- the result is committed. Regenerate it only if
the site's identity changes:

    python scripts/make_og_image.py

A headless browser does the drawing, so the card uses the site's own colours and
type and the repository keeps its single runtime dependency. Pillow would have
been the obvious alternative and was rejected for exactly that reason; an SVG
was rejected because X, Slack and Facebook do not render SVG in link previews.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "static" / "og.png"
WIDTH, HEIGHT = 1200, 630

BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)

CARD = """<!doctype html>
<meta charset="utf-8">
<style>
  @page { margin: 0 }
  html, body { margin: 0; padding: 0; }
  body {
    width: 1200px; height: 630px;
    background: #ffd23f; color: #15140f;
    font: 16px Georgia, "Times New Roman", serif;
    display: flex; flex-direction: column; justify-content: center;
    padding: 0 84px; box-sizing: border-box;
    border-bottom: 24px solid #15140f;
  }
  h1 {
    margin: 0;
    font: 800 132px/0.95 system-ui, -apple-system, "Segoe UI", Arial, sans-serif;
    letter-spacing: -0.04em; text-transform: uppercase;
  }
  p { margin: 28px 0 0; font-size: 40px; font-style: italic; max-width: 22ch; }
  .rule { width: 220px; height: 14px; background: #15140f; margin-top: 44px; }
</style>
<body>
  <h1>IT&nbsp;Brief</h1>
  <p>A daily digest of what happened in tech.</p>
  <div class="rule"></div>
</body>
"""


def browser() -> str:
    for candidate in BROWSERS:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")
    if found:
        return found
    sys.exit("No Chromium-based browser found; install Edge or Chrome, or draw the card by hand.")


def main() -> int:
    work = Path(tempfile.mkdtemp())
    card = work / "card.html"
    card.write_text(CARD, encoding="utf-8")
    shot = work / "og.png"

    subprocess.run(
        [
            browser(),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--screenshot={shot}",
            f"--window-size={WIDTH},{HEIGHT}",
            card.as_uri(),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if not shot.exists():
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(shot.read_bytes())
    print(f"wrote {TARGET} ({os.path.getsize(TARGET)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
