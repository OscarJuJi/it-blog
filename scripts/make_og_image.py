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

# The card is a window, like everything else on the site. Colours are copied
# from style.css rather than read from it: this runs once in a blue moon, by
# hand, and a CSS parser here would be more machinery than the problem deserves.
# If the palette changes there, change it here and re-run -- nothing else will.
CARD = """<!doctype html>
<meta charset="utf-8">
<style>
  @page { margin: 0 }
  html, body { margin: 0; padding: 0; }
  body {
    width: 1200px; height: 630px;
    background-color: #efe6d8;
    background-image:
      radial-gradient(50rem 30rem at 10% -10%, rgba(168,67,26,0.16), transparent 60%),
      radial-gradient(40rem 30rem at 95% 110%, rgba(125,47,16,0.14), transparent 62%);
    color: #2e2118;
    font: 16px Georgia, "Times New Roman", serif;
    display: flex; align-items: center; justify-content: center;
    box-sizing: border-box; padding: 54px;
  }
  .window {
    width: 100%; height: 100%;
    background: #fbf6ec;
    border: 1px solid #8a7359; border-radius: 14px;
    box-shadow: 0 6px 16px rgba(58,38,22,0.22), 0 22px 48px rgba(58,38,22,0.18);
    overflow: hidden;
    display: flex; flex-direction: column;
  }
  .bar {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 20px 16px 28px;
    background-image:
      linear-gradient(rgba(255,255,255,0.45), rgba(255,255,255,0) 58%),
      linear-gradient(180deg, #b04a17 0%, #7d2f10 100%);
    border-bottom: 1px solid #7d2f10;
    color: #fdf3e4;
    font: 700 26px/1 "Segoe UI", system-ui, Arial, sans-serif;
    text-shadow: 0 1px 0 rgba(0,0,0,0.3);
  }
  .controls { display: flex; gap: 8px; }
  .controls b {
    width: 30px; height: 24px; border-radius: 5px;
    border: 1px solid rgba(0,0,0,0.35);
    background-image: linear-gradient(180deg, rgba(255,255,255,0.55), rgba(255,255,255,0.05));
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.5);
  }
  .controls b:last-child { background-image: linear-gradient(180deg, #e8825f, #a33112); }
  .body { flex: 1; display: flex; flex-direction: column; justify-content: center; padding: 0 64px; }
  h1 {
    margin: 0;
    font: 800 128px/0.95 "Segoe UI", system-ui, -apple-system, Arial, sans-serif;
    letter-spacing: -0.04em; color: #2e2118;
    text-shadow: 0 2px 0 rgba(255,255,255,0.7);
  }
  p { margin: 30px 0 0; font-size: 38px; font-style: italic; color: #6d5b4b; max-width: 24ch; }
  .rule {
    width: 240px; height: 12px; margin-top: 40px; border-radius: 6px;
    background-image: linear-gradient(180deg, #c96a34, #a8431a);
  }
</style>
<body>
  <div class="window">
    <div class="bar">
      <span>IT Brief</span>
      <span class="controls"><b></b><b></b><b></b></span>
    </div>
    <div class="body">
      <h1>IT&nbsp;Brief</h1>
      <p>What mattered in tech, twice a week.</p>
      <div class="rule"></div>
    </div>
  </div>
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

    command = [
        browser(),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        # Its own profile, thrown away with the temp dir. Without one Edge reads
        # the real profile and can sit waiting on first-run state that never
        # arrives in headless.
        f"--user-data-dir={work / 'profile'}",
        "--force-device-scale-factor=1",
        f"--screenshot={shot}",
        f"--window-size={WIDTH},{HEIGHT}",
        card.as_uri(),
    ]

    # Twice, because the first call against a fresh profile writes the profile
    # and exits without drawing anything -- reproducibly, on Edge 2026-08. It
    # exits 0 while doing it, so only the missing file gives it away.
    for attempt in (1, 2):
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        if shot.exists():
            break
        print(f"attempt {attempt}: the browser drew nothing, retrying")

    if not shot.exists():
        print("the browser never wrote the screenshot", file=sys.stderr)
        return 1
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_bytes(shot.read_bytes())
    print(f"wrote {TARGET} ({os.path.getsize(TARGET)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
