# SpeechMap site

## Adding a new model

1. Scrape the new model with the `us_hard` dataset and analyze the results with the [LLM compliance tools](https://github.com/xlr8harder/llm-compliance) repo.
2. Point the build at the data checkout: `export SPEECHMAP_DATA_ROOT=/path/to/speechmap-data`.
3. Add model metadata to `model_metadata.json` (one JSON object per line).
4. Install deps: `uv sync`.
5. Generate the site: `uv run python preprocess.py`.
6. View locally with the Pages runtime: `npm run dev`, then open http://localhost:8789/.
7. Commit the generated site, review it, and deploy the prebuilt commit as described below.

## Build outputs

- Runtime JSON (tracked):
  - `data/metadata-core.json`
- Build-only artifacts (not tracked; stored in cache):
  - `/.cache/question-theme-summary/`
  - `/.cache/model-themes/`
  - `/.cache/theme_details/`

## Rebuild options

- Full build from analysis + metadata: `SPEECHMAP_DATA_ROOT=/path/to/speechmap-data uv run python preprocess.py`
- Static-only rebuild from cache artifacts: `uv run python preprocess.py --static-only`
- Cached rebuild of all static HTML while preserving response shards:
  `uv run python preprocess.py --static-only --no-shards`
- Static shell/core pages without per-theme pages or shard rewrites:
  `uv run python preprocess.py --static-only --no-themes`
- Lab pages only: `uv run python preprocess.py --labs-only`
- Refresh the Substack cache and home page only:
  `uv run python preprocess.py --substack-refresh`

Sharding does not require every change to run a full analysis build. Use
`--no-shards` when page chrome or templates changed but response-card rendering
and source data did not. Use `--no-themes` when theme pages themselves are
unaffected. A future data-incremental builder can go further and update only
the affected theme/shard buckets.

## Preview and deploy

Building and deploying are deliberately separate. The deploy helper never runs
`preprocess.py`; it operates on the prebuilt tree passed with `--artifact-dir`.

- Default local Pages preview (including Functions):
  `uv run python tools/deploy_pages.py`
- Local preview of a staged tree:
  `uv run python tools/deploy_pages.py --artifact-dir /path/to/stage`
- Remote Pages preview followed by an interactive production promotion:
  `uv run python tools/deploy_pages.py deploy --artifact-dir /path/to/clean/worktree`
- Production upload without the remote Pages preview:
  `uv run python tools/deploy_pages.py deploy --artifact-dir /path/to/clean/worktree --skip-pages-preview`
- Remote Pages preview only:
  `uv run python tools/deploy_pages.py deploy --artifact-dir /path/to/clean/worktree --preview-only`

Production artifacts must be clean Git worktrees so each deployment can record
the exact site commit and tree. Deployment receipts live in `deployments/`.
Cloudflare Git-triggered production and preview deployments are disabled; Git
remains the source of history, while Wrangler direct upload is the transport.
