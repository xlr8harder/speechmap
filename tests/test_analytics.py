from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from preprocess import _page_head


ANALYTICS_BEACON_URL = "https://static.cloudflareinsights.com/beacon.min.js"


def test_page_head_relies_on_cloudflare_automatic_analytics():
    head = _page_head("Test", "https://speechmap.ai/test/")

    assert ANALYTICS_BEACON_URL not in head
    assert "data-cf-beacon" not in head


def test_checked_in_html_does_not_embed_manual_analytics():
    generated_files = [
        path
        for path in REPO_ROOT.rglob("*.html")
        if not any(part.startswith(".") or part == "node_modules" for part in path.parts)
    ]
    offenders = [
        path.relative_to(REPO_ROOT)
        for path in generated_files
        if ANALYTICS_BEACON_URL in path.read_text(encoding="utf-8")
    ]

    assert not offenders, (
        "Cloudflare automatic analytics is enabled; remove the manually embedded "
        f"beacon from generated HTML. First offenders: {offenders[:10]}"
    )
