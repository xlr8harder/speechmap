# Adding a new model:
1. Scrape the new model with the `us_hard` dataset and analyze the results with the [LLM compliance tools](github.com/xlr8harder/llm-compliance) repo.
2. ensure `./analysis` is symlinked to the llm-compliance checkout `analysis` subdir.
3. Add model metadata do `metadata_models.json`
4. Run `python preprocess.py`
5. View locally: `python -m http.server 8000` then browse to [localhost](http://localhost:8000/)
6. Commit and push.
7. Deployment happens automatically.
