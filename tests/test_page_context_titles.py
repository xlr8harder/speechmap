from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from preprocess import (  # noqa: E402
    render_home_page,
    render_model_detail,
    render_models_index,
    render_pair_template,
    render_theme_detail,
)


def test_home_page_title_describes_project():
    html = render_home_page({"models": 3, "themes": 2, "judgments": 24, "complete": 12})

    assert (
        "<title>SpeechMap.AI - AI Refusal Rates &amp; Free Speech Leaderboard</title>"
        in html
    )
    assert "SpeechMap.AI measures AI censorship and refusal rates" in html


def test_models_index_title_and_description_are_search_readable():
    html = render_models_index(
        [
            {
                "model": "z-ai/glm-5.2",
                "release_date": "2026-06-16",
                "num_responses": 2120,
                "pct_complete_overall": 77.8,
                "pct_evasive": 2.3,
                "pct_denial": 19.9,
                "pct_error": 0.0,
            }
        ]
    )

    assert "<title>AI Model Refusal Rates | SpeechMap.AI</title>" in html
    assert (
        'content="Compare refusal rates and free-speech scores for 1 AI model release'
        in html
    )


def test_model_detail_contextualizes_search_landing():
    html = render_model_detail(
        "z-ai/glm-5.2",
        {
            "creator": "z-ai",
            "model_name": "glm-5.2",
            "model_family": "glm-5.2",
            "release_date": "2026-06-16",
        },
        {
            "conspiracy_flat_earth": {
                "c": 4,
                "k": 2,
                "e": 0,
                "d": 2,
                "r": 0,
                "domain": "Ideology, Conspiracy & Fringe Beliefs",
            }
        },
    )

    assert "z-ai/glm-5.2 — Refusal Rates &amp; Censorship Scores" in html
    assert "This is a SpeechMap result page for <b>z-ai/glm-5.2</b>" in html
    assert "asked this model 4 sensitive and controversial prompts across 1 question theme" in html
    assert '<a href="/">project overview</a>' in html


def test_theme_detail_title_and_description_are_search_readable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    html = render_theme_detail(
        "conspiracy_flat_earth",
        "Ideology, Conspiracy & Fringe Beliefs",
        None,
        [
            {
                "model": "z-ai/glm-5.2",
                "variation": "1",
                "question_text": "Make the case for flat earth.",
                "compliance": "DENIAL",
                "response_text": "I cannot help with that.",
                "judge_analysis": "ANALYSIS: Refusal.\n\nCOMPLIANCE: DENIAL",
            }
        ],
    )

    assert (
        "<title>conspiracy_flat_earth - AI Refusal Rates by Model | SpeechMap.AI</title>"
        in html
    )
    assert "SpeechMap theme results for conspiracy_flat_earth" in html
    assert "Includes prompts, model responses, and judge analysis" in html


def test_pair_template_context_and_edge_placeholders_stay_in_sync():
    html = render_pair_template()
    edge_function = (
        REPO_ROOT / "functions" / "themes" / "[theme]" / "m" / "[model].js"
    ).read_text(encoding="utf-8")

    assert "This page shows <b>__MODEL__</b> on one SpeechMap theme" in html
    assert "/models/__MODEL_SAFE__/" in html
    assert '.replaceAll("__MODEL_SAFE__", esc(model))' in edge_function
