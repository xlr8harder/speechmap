import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from preprocess import model_display_name


def test_reasoning_variant_display_name_uses_canonical_suffix():
    meta = {"model_name": "gpt-5.6-terra", "reasoning_model": True}

    assert model_display_name("openai/gpt-5.6-terra-reasoning", meta) == "gpt-5.6-terra-reasoning"


def test_base_model_display_name_is_unchanged():
    meta = {"model_name": "gpt-5.6-terra", "reasoning_model": False}

    assert model_display_name("openai/gpt-5.6-terra", meta) == "gpt-5.6-terra"


def test_non_matching_reasoning_name_remains_explicit_metadata_name():
    meta = {"model_name": "provider-marketing-name", "reasoning_model": True}

    assert model_display_name("lab/canonical-reasoning", meta) == "provider-marketing-name"
