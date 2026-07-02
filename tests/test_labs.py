"""Lab hub pages and leaderboard exploration links."""


def test_leaderboard_links_to_lab_page(page, site_url):
    page.goto(site_url + "/labs/")
    first = page.locator(".leaderboard-table td.lab-name a").first
    name = first.inner_text().strip()
    first.click()
    page.wait_for_url("**/labs/**")
    assert page.locator("h1", has_text=name).count() >= 1
    # Lab page carries a sortable model table and a timeline link.
    assert page.locator(".data-table-block table.sm-table tbody tr").count() >= 1
    assert page.locator('a[href^="/timeline/?highlight="]').count() == 1


def test_lab_page_table_filtered_to_lab(page, site_url):
    page.goto(site_url + "/labs/mistralai/")
    models = page.eval_on_selector_all(
        ".sm-table tbody tr",
        "rows => rows.map(r => r.getAttribute('data-s-model'))",
    )
    assert models and all(m.startswith("mistralai/") for m in models)


def test_models_filter_deep_link(page, site_url):
    page.goto(site_url + "/models/?filter=mistralai/")
    assert page.locator("input.table-filter").input_value() == "mistralai/"
    visible = page.eval_on_selector_all(
        ".sm-table tbody tr:not([hidden])",
        "rows => rows.map(r => r.getAttribute('data-s-model'))",
    )
    assert visible and all("mistralai/" in m for m in visible)
