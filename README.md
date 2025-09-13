# Adding a new model

1. Scrape the new model with the `us_hard` dataset and analyze the results with the [LLM compliance tools](https://github.com/xlr8harder/llm-compliance) repo.
2. Ensure `./analysis` is symlinked to the llm-compliance checkout `analysis` subdir.
3. Add model metadata to `model_metadata.json` (one JSON object per line).
4. Install deps (first time): `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.
5. Generate the site: `python3 preprocess.py`.
6. View locally: `python3 -m http.server -d . 8000` then open http://localhost:8000/.
7. Commit and push. Deployment happens automatically.

## Build outputs
- Runtime JSON (tracked):
  - `data/metadata-core.json`
  - `data/model-domain-summary.json`
- Build-only artifacts (not tracked; stored in cache):
  - `/.cache/question-theme-summary/`
  - `/.cache/model-themes/`
  - `/.cache/theme_details/`

## Rebuild options
- Full build from analysis + metadata: `python3 preprocess.py`
- Static-only rebuild from cache artifacts: `python3 preprocess.py --static-only`
