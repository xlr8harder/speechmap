"""Timeline: legend chips, multi-pin highlighting, URL param sync."""

import json

from conftest import REPO_ROOT


def wait_for_chart(page):
    page.wait_for_function("() => !!window.__timelineChart", timeout=10000)


def dataset_count(page):
    return page.evaluate("() => window.__timelineChart.data.datasets.length")


def colored_lab_count():
    count = 0
    with (REPO_ROOT / "lab_metadata.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if line.strip() and json.loads(line).get("color"):
                count += 1
    return count


def test_legend_chips_render(page, site_url):
    page.goto(site_url + "/timeline/")
    wait_for_chart(page)
    chips = page.locator("#timeline-legend button.tl-chip[data-lab]")
    assert chips.count() == colored_lab_count()  # colored tier; Other is a static swatch
    assert page.locator("#timeline-legend .tl-swatch").is_visible()
    assert page.locator("#timeline-clear-highlights").is_hidden()


def test_chip_multi_pin_and_clear(page, site_url):
    page.goto(site_url + "/timeline/")
    wait_for_chart(page)
    assert dataset_count(page) == 2  # scatter + overall trend
    page.click('.tl-chip[data-lab="z-ai"]')
    page.click('.tl-chip[data-lab="anthropic"]')
    page.wait_for_function("() => location.search.includes('highlight')")
    pinned = page.evaluate("() => window.__timelinePinned()")
    assert set(pinned) == {"z-ai", "anthropic"}
    assert "z-ai" in page.url and "anthropic" in page.url
    assert dataset_count(page) == 4, "one trajectory line per pinned lab"
    clear = page.locator("#timeline-clear-highlights")
    assert clear.is_visible()
    clear.click()
    page.wait_for_function("() => !location.search.includes('highlight')")
    assert page.evaluate("() => window.__timelinePinned()") == []
    assert dataset_count(page) == 2


def test_highlight_param_restores_pins(page, site_url):
    page.goto(site_url + "/timeline/?highlight=anthropic,openai")
    wait_for_chart(page)
    assert set(page.evaluate("() => window.__timelinePinned()")) == {"anthropic", "openai"}
    assert "pinned" in (page.locator('.tl-chip[data-lab="anthropic"]').get_attribute("class") or "")


def test_highlight_select_adds_temp_chip(page, site_url):
    page.goto(site_url + "/timeline/")
    wait_for_chart(page)
    # Pick some lab that has no prerendered chip.
    lab = page.evaluate(
        """() => {
          const sel = document.getElementById('timeline-highlight-creator-filter');
          const chips = new Set(Array.from(document.querySelectorAll('.tl-chip[data-lab]')).map(c => c.dataset.lab));
          return Array.from(sel.options).map(o => o.value).find(v => v !== 'none' && !chips.has(v));
        }"""
    )
    assert lab
    page.select_option("#timeline-highlight-creator-filter", lab)
    page.wait_for_selector(f'.tl-chip-temp[data-lab="{lab}"]')
    assert lab in page.evaluate("() => window.__timelinePinned()")
    assert page.locator("#timeline-highlight-creator-filter").input_value() == "none"
    # Clicking the temp chip removes it and the pin.
    page.click(f'.tl-chip-temp[data-lab="{lab}"]')
    assert page.locator(f'.tl-chip-temp[data-lab="{lab}"]').count() == 0
    assert lab not in page.evaluate("() => window.__timelinePinned()")


def test_metric_select_updates_url(page, site_url):
    page.goto(site_url + "/timeline/")
    wait_for_chart(page)
    page.select_option("#timeline-metric-filter", "pct_denial")
    page.wait_for_url("**?metric=pct_denial")
    wait_for_chart(page)
