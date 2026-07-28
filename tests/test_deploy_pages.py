from pathlib import Path

import pytest

from tools import deploy_pages


def make_artifact(root: Path) -> Path:
    for relative in deploy_pages.REQUIRED_ARTIFACT_PATHS:
        path = root / relative
        if relative == "functions":
            path.mkdir(parents=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
    return root


def test_default_action_is_local_preview():
    args = deploy_pages.parse_args([])
    assert args.action == "local"
    assert args.artifact_dir == deploy_pages.REPO_ROOT


def test_remote_preview_can_be_skipped():
    args = deploy_pages.parse_args(["deploy", "--skip-pages-preview", "--yes"])
    assert args.action == "deploy"
    assert args.skip_pages_preview is True
    assert args.yes is True


def test_conflicting_remote_preview_options_are_rejected():
    with pytest.raises(SystemExit):
        deploy_pages.parse_args(
            ["deploy", "--preview-only", "--skip-pages-preview"]
        )


def test_validate_artifact_accepts_required_structure(tmp_path):
    artifact = make_artifact(tmp_path)
    assert deploy_pages.validate_artifact(artifact) == artifact.resolve()


def test_validate_artifact_lists_missing_paths(tmp_path):
    with pytest.raises(ValueError, match="index.html"):
        deploy_pages.validate_artifact(tmp_path)
