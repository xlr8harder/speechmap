#!/usr/bin/env python3
"""Screenshot rendered site pages for design review.

Serves the repo root on an ephemeral port and captures pages with Playwright.

Usage:
    uv run python tools/screenshot.py                      # default page set
    uv run python tools/screenshot.py / /models/ --mobile
    uv run python tools/screenshot.py /themes/ --width 1100 --full-page

One-time setup:
    uv sync                       # installs the dev dependency group
    uv run playwright install chromium

Output lands in .screenshots/ (gitignored) unless --out is given.
"""
import argparse
import functools
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PAGES = ["/", "/labs/", "/models/", "/themes/", "/timeline/"]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def start_server():
    handler = functools.partial(QuietHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def slug(path):
    s = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-")
    return s or "home"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pages", nargs="*", default=None, help="site paths to capture (default: main pages)")
    ap.add_argument("--out", default=str(REPO_ROOT / ".screenshots"), help="output directory")
    ap.add_argument("--width", type=int, default=1440, help="viewport width (default 1440)")
    ap.add_argument("--height", type=int, default=1000, help="viewport height (default 1000)")
    ap.add_argument("--mobile", action="store_true", help="also capture a 390px-wide viewport")
    ap.add_argument("--full-page", action="store_true", help="capture full page height")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    pages = args.pages or DEFAULT_PAGES
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    server, base = start_server()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            viewports = [(args.width, args.height, "")]
            if args.mobile:
                viewports.append((390, 844, "-mobile"))
            for width, height, suffix in viewports:
                page = browser.new_page(viewport={"width": width, "height": height})
                for path in pages:
                    page.goto(base + path, wait_until="networkidle")
                    page.wait_for_timeout(500)
                    dest = out / f"{slug(path)}{suffix}.png"
                    page.screenshot(path=str(dest), full_page=args.full_page)
                    print(dest)
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
