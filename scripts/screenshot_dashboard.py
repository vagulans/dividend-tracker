"""Capture a full-page PNG of the demo dashboard for README documentation."""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    demo = root / "screenshots" / "_dashboard_demo.html"
    out = root / "screenshots" / "dashboard.png"
    if not demo.exists():
        print(f"error: {demo} not found; run scripts/build_demo_dashboard.py first", file=sys.stderr)
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1600, "height": 1000}, device_scale_factor=1.5)
        page = context.new_page()
        page.goto(demo.resolve().as_uri())
        page.wait_for_selector(".js-plotly-plot .bars, .js-plotly-plot .scatterlayer", timeout=15000)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(out), full_page=True)
        browser.close()

    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
