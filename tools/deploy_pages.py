#!/usr/bin/env python3
"""Preview or deploy an already-built SpeechMap Pages artifact.

This intentionally does not run preprocess.py. Building and deploying are
separate operations so a lightweight/partial build can be reviewed and
deployed without accidentally triggering a full site regeneration.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
WRANGLER = REPO_ROOT / "node_modules" / ".bin" / "wrangler"
DEFAULT_PROJECT = "speechmap"
DEFAULT_PRODUCTION_BRANCH = "main"
SMOKE_PATHS = (
    "/",
    "/models/",
    "/themes/",
    "/timeline/",
    "/data/metadata-core.json",
)
REQUIRED_ARTIFACT_PATHS = (
    "index.html",
    "models/index.html",
    "themes/index.html",
    "timeline/index.html",
    "data/metadata-core.json",
    "functions",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Preview an existing site tree locally (the default), or deploy "
            "that same tree to Cloudflare Pages."
        )
    )
    parser.add_argument(
        "action",
        choices=("local", "deploy"),
        nargs="?",
        default="local",
        help="local is the default; deploy performs a Pages preview and production upload",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=REPO_ROOT,
        help="prebuilt site root (default: repository root)",
    )
    parser.add_argument("--project-name", default=DEFAULT_PROJECT)
    parser.add_argument("--production-branch", default=DEFAULT_PRODUCTION_BRANCH)
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument(
        "--skip-pages-preview",
        action="store_true",
        help="deploy directly to production without first creating a remote Pages preview",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="create and verify a remote Pages preview, then stop",
    )
    parser.add_argument(
        "--preview-branch",
        help="preview branch label (default: generated from commit and UTC time)",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="do not prompt before the production upload",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print commands without starting Wrangler",
    )
    args = parser.parse_args(argv)
    if args.preview_only and args.skip_pages_preview:
        parser.error("--preview-only and --skip-pages-preview cannot be combined")
    if args.action == "local" and (args.preview_only or args.skip_pages_preview or args.yes):
        parser.error("remote-deployment options require the deploy action")
    return args


def validate_artifact(artifact_dir: Path) -> Path:
    artifact_dir = artifact_dir.expanduser().resolve()
    if not artifact_dir.is_dir():
        raise ValueError(f"artifact directory does not exist: {artifact_dir}")
    missing = [
        relative
        for relative in REQUIRED_ARTIFACT_PATHS
        if not (artifact_dir / relative).exists()
    ]
    if missing:
        raise ValueError(
            f"{artifact_dir} is not a complete SpeechMap artifact; missing: "
            + ", ".join(missing)
        )
    return artifact_dir


def run(
    command: list[str],
    *,
    cwd: Path = REPO_ROOT,
    capture: bool = False,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(str(part) for part in command), flush=True)
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture,
    )


def git_value(artifact_dir: Path, expression: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(artifact_dir), "rev-parse", expression],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def artifact_provenance(artifact_dir: Path) -> tuple[str, str, bool]:
    commit = git_value(artifact_dir, "HEAD")
    tree = git_value(artifact_dir, "HEAD^{tree}")
    status = subprocess.run(
        [
            "git",
            "-C",
            str(artifact_dir),
            "-c",
            "core.filemode=false",
            "status",
            "--porcelain",
            "--untracked-files=no",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return commit, tree, bool(status.stdout.strip())


def wrangler_command(*parts: str) -> list[str]:
    if not WRANGLER.is_file():
        raise ValueError(
            f"Wrangler is not installed at {WRANGLER}; run npm install first"
        )
    return [str(WRANGLER), *parts]


def deployment_list(project_name: str) -> list[dict[str, str]]:
    result = run(
        wrangler_command(
            "pages",
            "deployment",
            "list",
            "--project-name",
            project_name,
            "--json",
        ),
        capture=True,
    )
    return json.loads(result.stdout)


def new_deployment(
    before_ids: set[str],
    project_name: str,
    expected_environment: str,
) -> dict[str, str]:
    candidates = [
        item
        for item in deployment_list(project_name)
        if item["Id"] not in before_ids
        and item["Environment"].casefold() == expected_environment.casefold()
    ]
    if len(candidates) != 1:
        raise RuntimeError(
            f"expected one new {expected_environment} deployment, found "
            f"{len(candidates)}"
        )
    return candidates[0]


def deploy_once(
    artifact_dir: Path,
    *,
    project_name: str,
    branch: str,
    commit: str,
    message: str,
    expected_environment: str,
) -> dict[str, str]:
    before_ids = {item["Id"] for item in deployment_list(project_name)}
    run(
        wrangler_command(
            "pages",
            "deploy",
            str(artifact_dir),
            "--project-name",
            project_name,
            "--branch",
            branch,
            "--commit-hash",
            commit,
            "--commit-message",
            message,
            "--commit-dirty=false",
        )
    )
    return new_deployment(before_ids, project_name, expected_environment)


def fetch_digest(base_url: str, path: str) -> str:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        headers={"User-Agent": "speechmap-deploy-check/1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        return hashlib.sha256(response.read()).hexdigest()


def smoke(base_url: str) -> dict[str, str]:
    print(f"Checking {base_url}", flush=True)
    digests = {}
    for path in SMOKE_PATHS:
        digests[path] = fetch_digest(base_url, path)
        print(f"  200 {path}", flush=True)
    return digests


def write_receipt(
    *,
    production: dict[str, str],
    preview: dict[str, str] | None,
    previous_production_id: str | None,
    commit: str,
    tree: str,
    project_name: str,
    production_branch: str,
) -> Path:
    now = dt.datetime.now(dt.UTC)
    deployed_at = now.isoformat()
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    receipt_dir = REPO_ROOT / "deployments"
    receipt_dir.mkdir(exist_ok=True)
    receipt_path = receipt_dir / f"{stamp}-{production['Id']}.json"
    receipt = {
        "schema_version": 1,
        "deployed_at": deployed_at,
        "project": project_name,
        "environment": "production",
        "deployment_id": production["Id"],
        "deployment_url": production["Deployment"],
        "deployment_source": "ad_hoc",
        "site_commit": commit,
        "site_tree": tree,
        "production_branch": production_branch,
        "preview_deployment_id": preview["Id"] if preview else None,
        "previous_production_deployment_id": previous_production_id,
        "pages_config": {
            "wrangler_config": "wrangler.toml",
            "compatibility_date": "2025-04-12",
        },
        "data_provenance": {
            "kind": "generated_site_commit",
            "data_commit": None,
            "note": (
                "The legacy repository stores generated data in the site commit; "
                "a separate source-data commit was not recorded."
            ),
        },
    }
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote deployment receipt: {receipt_path}", flush=True)
    return receipt_path


def local_preview(args: argparse.Namespace, artifact_dir: Path) -> int:
    command = wrangler_command(
        "pages",
        "dev",
        str(artifact_dir),
        "--port",
        str(args.port),
    )
    run(command, dry_run=args.dry_run)
    return 0


def deploy(args: argparse.Namespace, artifact_dir: Path) -> int:
    commit, tree, dirty = artifact_provenance(artifact_dir)
    if dirty:
        raise ValueError(
            "artifact has tracked changes; commit the generated tree or deploy "
            "from a clean detached worktree so the receipt identifies exact bytes"
        )

    if args.dry_run:
        preview_branch = args.preview_branch or f"pages-preview-{commit[:7]}-DRYRUN"
        if not args.skip_pages_preview:
            run(
                wrangler_command(
                    "pages",
                    "deploy",
                    str(artifact_dir),
                    "--project-name",
                    args.project_name,
                    "--branch",
                    preview_branch,
                    "--commit-hash",
                    commit,
                ),
                dry_run=True,
            )
        if not args.preview_only:
            run(
                wrangler_command(
                    "pages",
                    "deploy",
                    str(artifact_dir),
                    "--project-name",
                    args.project_name,
                    "--branch",
                    args.production_branch,
                    "--commit-hash",
                    commit,
                ),
                dry_run=True,
            )
        return 0

    existing = deployment_list(args.project_name)
    previous_production_id = next(
        (
            item["Id"]
            for item in existing
            if item["Environment"].casefold() == "production"
        ),
        None,
    )
    preview = None
    preview_digests = None
    if not args.skip_pages_preview:
        now = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
        preview_branch = args.preview_branch or f"pages-preview-{commit[:7]}-{now}"
        preview = deploy_once(
            artifact_dir,
            project_name=args.project_name,
            branch=preview_branch,
            commit=commit,
            message="Direct-upload preview",
            expected_environment="preview",
        )
        preview_digests = smoke(preview["Deployment"])
        print(
            f"Remote preview ready: {preview['Deployment']} ({preview['Id']})",
            flush=True,
        )
        if args.preview_only:
            return 0

    if not args.yes:
        answer = input(
            f"Deploy commit {commit[:12]} to {args.project_name} production? [y/N] "
        )
        if answer.casefold() not in {"y", "yes"}:
            print("Production deployment cancelled.", flush=True)
            return 1

    production = deploy_once(
        artifact_dir,
        project_name=args.project_name,
        branch=args.production_branch,
        commit=commit,
        message="Direct-upload production deployment",
        expected_environment="production",
    )
    production_digests = smoke(production["Deployment"])
    if preview_digests is not None and production_digests != preview_digests:
        raise RuntimeError("production output differs from the approved Pages preview")
    write_receipt(
        production=production,
        preview=preview,
        previous_production_id=previous_production_id,
        commit=commit,
        tree=tree,
        project_name=args.project_name,
        production_branch=args.production_branch,
    )
    print(
        f"Production deployed: {production['Deployment']} ({production['Id']})",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        artifact_dir = validate_artifact(args.artifact_dir)
        if args.action == "local":
            return local_preview(args, artifact_dir)
        return deploy(args, artifact_dir)
    except (ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
