"""Top navigation: tab clicks land on the right page with the right active tab."""
import pytest

TABS = [
    ("About", "/"),
    ("Leaderboard", "/labs/"),
    ("Models", "/models/"),
    ("Themes", "/themes/"),
    ("Timeline", "/timeline/"),
    ("Resources & Data", "/resources/"),
]


def test_acknowledgments_reachable_from_resources(page, site_url):
    page.goto(site_url + "/resources/")
    page.click('a.resource-card[href="/acknowledgments/"]')
    page.wait_for_url("**/acknowledgments/")


@pytest.mark.parametrize("label,path", TABS)
def test_tab_click_navigates(page, site_url, label, path):
    page.goto(site_url + "/")
    page.click(f'nav.view-selector button:text-is("{label}")')
    page.wait_for_url(f"**{path}")
    active = page.locator("nav.view-selector button.active")
    assert active.count() == 1
    assert active.inner_text().strip() == label


def test_theme_page_has_outcome_columns(page, site_url, a_theme_slug):
    page.goto(f"{site_url}/themes/{a_theme_slug}/")
    cols = page.locator(".verdict-columns .vg-col")
    assert cols.count() >= 2
    href = page.locator(".verdict-columns a.mchip").first.get_attribute("href")
    assert f"/themes/{a_theme_slug}/m/" in href


def test_legacy_model_anchor_redirects_to_pair_page(page, site_url, a_theme_slug):
    """Old deep links (/themes/<t>/#model-<id>) must land on the pair URL."""
    page.goto(f"{site_url}/themes/{a_theme_slug}/")
    chip_id = page.evaluate(
        "() => { const e = document.querySelectorAll('a.mchip[id^=model-]');"
        " return e[e.length - 1].id; }"
    )
    slug = chip_id.removeprefix("model-")
    page.goto(f"{site_url}/themes/{a_theme_slug}/#{chip_id}")
    page.wait_for_url(f"**/themes/{a_theme_slug}/m/{slug}/", timeout=5000)
