import preprocess


def test_analysis_dir_prefers_speechmap_data_root(monkeypatch):
    monkeypatch.setenv("SPEECHMAP_DATA_ROOT", "/tmp/speechmap-data")

    assert preprocess.get_analysis_dir() == "/tmp/speechmap-data/analysis"


def test_analysis_dir_uses_legacy_default_without_data_root(monkeypatch):
    monkeypatch.delenv("SPEECHMAP_DATA_ROOT", raising=False)

    assert preprocess.get_analysis_dir() == preprocess.ANALYSIS_DIR


def test_static_only_no_shards_preserves_theme_shards(monkeypatch):
    calls = []
    monkeypatch.setattr(
        preprocess,
        "generate_static_pages_from_artifacts",
        lambda **kwargs: calls.append(kwargs),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["preprocess.py", "--static-only", "--no-shards"],
    )

    preprocess.main()

    assert calls == [
        {
            "skip_theme_pages": False,
            "preserve_theme_shards": True,
        }
    ]
