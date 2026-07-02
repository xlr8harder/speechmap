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


def test_model_anchor_lands_near_top(page, site_url, a_theme_slug):
    """Deep link with #model-... should end up focused near the viewport top."""
    page.goto(f"{site_url}/themes/{a_theme_slug}/")
    anchor_id = page.evaluate(
        "() => { const el = document.querySelector('[id^=model-]'); return el ? el.id : null; }"
    )
    assert anchor_id, "theme page has no model anchors"
    page.goto(f"{site_url}/themes/{a_theme_slug}/#{anchor_id}")
    page.wait_for_load_state("load")
    page.wait_for_timeout(400)  # script.js re-anchors at 0ms and 250ms after load
    top = page.evaluate(
        "id => document.getElementById(id).getBoundingClientRect().top", anchor_id
    )
    assert -2 <= top <= 120, f"anchor {anchor_id} at viewport offset {top}"
