"""Data table behavior: sorting (headers, chips, mobile toolbar) and filtering."""


def visible_values(page, key, limit=8):
    return page.eval_on_selector_all(
        ".sm-table tbody tr:not([hidden])",
        f"(rows) => rows.slice(0, {limit}).map(r => r.getAttribute('data-s-{key}'))",
    )


def test_models_default_sort_is_release_desc(page, site_url):
    page.goto(site_url + "/models/")
    dates = visible_values(page, "released")
    assert dates == sorted(dates, reverse=True)


def test_header_sort_toggles(page, site_url):
    page.goto(site_url + "/models/")
    page.click('th[data-sort-key="complete"]')
    vals = [float(v) for v in visible_values(page, "complete")]
    assert vals == sorted(vals, reverse=True), "first click sorts % complete desc"
    page.click('th[data-sort-key="complete"]')
    vals = [float(v) for v in visible_values(page, "complete")]
    assert vals == sorted(vals), "second click flips to asc"


def test_chip_sort_by_denial(page, site_url):
    page.goto(site_url + "/models/")
    page.click('.vb-chip[data-sort-key="denial"]')
    vals = [float(v) for v in visible_values(page, "denial")]
    assert vals == sorted(vals, reverse=True)


def test_filter_substring_and_regex(page, site_url):
    page.goto(site_url + "/models/")
    page.fill("input.table-filter", "claude")
    rows = visible_values(page, "model", limit=1000)
    assert rows and all("claude" in r for r in rows)
    page.fill("input.table-filter", "/gpt-4(o|\\.1)/")
    rows = visible_values(page, "model", limit=1000)
    assert rows and all(("gpt-4o" in r or "gpt-4.1" in r) for r in rows)
    page.fill("input.table-filter", "")
    assert len(visible_values(page, "model", limit=10000)) > 100


def test_mobile_toolbar_sorts(page, site_url):
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(site_url + "/models/")
    sort_select = page.locator("select.table-sort")
    assert sort_select.is_visible(), "sort toolbar should be visible on mobile"
    value = sort_select.locator("option", has_text="% Complete").get_attribute("value")
    sort_select.select_option(value)
    vals = [float(v) for v in visible_values(page, "complete")]
    assert vals == sorted(vals, reverse=True)
    page.click("button.table-sort-dir")
    vals = [float(v) for v in visible_values(page, "complete")]
    assert vals == sorted(vals)


def test_themes_table_present_with_default_sort(page, site_url):
    page.goto(site_url + "/themes/")
    vals = [float(v) for v in visible_values(page, "complete")]
    assert vals == sorted(vals), "themes default to % complete ascending"
