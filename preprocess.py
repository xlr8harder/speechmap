# preprocess.py
import json
import os
from glob import glob
import re
import sys
import gzip
import math
import shutil
from collections import defaultdict
import unicodedata
import html as htmlmod
from urllib.parse import quote_plus
from datetime import date
import argparse

# --- Configuration ---
ANALYSIS_DIR = "../llm-compliance/analysis"
MODEL_METADATA_FILE = "model_metadata.json"
LAB_METADATA_FILE = "lab_metadata.jsonl"
MODEL_METADATA_SKIP_FLAG = "skip"

# Cache directory for build-only artifacts (not needed at runtime; not committed)
CACHE_DIR = ".cache"


# Phase 1 split-output locations
DATA_DIR = "data"
# Runtime JSON used by the client at runtime (keep under /data)
OUTPUT_CORE_METADATA_FILE = os.path.join(DATA_DIR, "metadata-core.json")

# Build-only artifacts moved under /.cache
OUTPUT_QTHEME_SUMMARY_DIR = os.path.join(CACHE_DIR, "question-theme-summary")
OUTPUT_MODEL_THEMES_DIR = os.path.join(CACHE_DIR, "model-themes")
OUTPUT_THEME_DETAIL_DIR = os.path.join(CACHE_DIR, "theme_details")
SUBSTACK_FEED_URL = "https://speechmap.substack.com/feed"
SUBSTACK_CACHE_FILE = os.path.join(CACHE_DIR, "substack-posts.json")

# Phase 2 static site generation
SITE_BASE_URL = "https://speechmap.ai"
STATIC_MODELS_DIR = "models"
STATIC_THEMES_DIR = "themes"
STATIC_LABS_DIR = "labs"
THEME_SAMPLE_LIMIT = 16
# MAX_RECORDS_PER_FILE = 20000 # No longer needed
COMPLIANCE_ORDER = ["COMPLETE", "EVASIVE", "DENIAL", "ERROR", "UNKNOWN"]
ID_REGEX = re.compile(r"^(.*?)(\d)$")
ERROR_MSG_CENSORSHIP = "ERROR: This typically indicates moderation or censorship systems have prevented the model from replying, or cancelled a response."
JUDGE_ANALYSIS_FOR_ERROR = "N/A (Response was an ERROR)"
JUDGE_ANALYSIS_FOR_ORIGINAL_MODERATION = "N/A (Original response was stopped by provider moderation/classifier)"
MODERATION_ERROR_TEXT_RE = re.compile(
    r"("
    r"usage policy|"
    r"requires moderation|"
    r"input was flagged|"
    r"prompt was flagged|"
    r"output data may contain inappropriate content|"
    r"input data may contain inappropriate content|"
    r"data_inspection_failed|"
    r"prohibited_content|"
    r"content[_ -]?filter|"
    r"safety policy|"
    r"policy violation|"
    r"blocked by (?:safety|moderation)|"
    r"\bmoderation\b"
    r")",
    re.IGNORECASE,
)
LAB_STANDINGS_WINDOW_MONTHS = 6
LAB_STANDINGS_HALFLIFE_MONTHS = 3
# Derived EMA alpha so weight halves every LAB_STANDINGS_HALFLIFE_MONTHS buckets
LAB_STANDINGS_EMA_ALPHA = 1 - (0.5 ** (1 / LAB_STANDINGS_HALFLIFE_MONTHS))
CLOUDFLARE_ANALYTICS_SNIPPET = (
    "<!-- Cloudflare Web Analytics -->"
    "<script defer src='https://static.cloudflareinsights.com/beacon.min.js' "
    "data-cf-beacon='{\"token\": \"d1b43eda5db840b380aeaed5d798d3a2\"}'></script>"
    "<!-- End Cloudflare Web Analytics -->"
)


def generate_safe_id(text):
    # Re-purposed slightly for filesystem-safe filenames from grouping keys
    text_str = str(text) if text is not None else ""
    # Normalize unicode characters
    nfkd_form = unicodedata.normalize("NFKD", text_str)
    only_ascii = nfkd_form.encode("ASCII", "ignore").decode("ASCII")
    # Replace non-alphanumeric with hyphen, collapse multiple hyphens
    safe_text = re.sub(r"[^\w-]+", "-", only_ascii.lower().strip())
    safe_text = re.sub(r"-+", "-", safe_text)
    # Ensure it's not empty, max length (e.g., 100 chars)
    safe_text = safe_text[:100]
    return safe_text if safe_text else "id"


def load_model_metadata(filepath):
    metadata = {}
    if not os.path.exists(filepath):
        print(f"Warning: Model metadata file not found: {filepath}")
        return metadata

    print(f"Loading model metadata from {filepath}...")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                try:
                    data = json.loads(line.strip())
                    identifier = data.get("model_identifier")
                    if identifier:
                        metadata[identifier] = data
                    else:
                        print(f"  Warning: Missing 'model_identifier' on line {i+1} in {filepath}")
                except json.JSONDecodeError as e:
                    print(f"  Error parsing JSON on line {i+1} in {filepath}: {e}")
                except Exception as e:
                    print(f"  Unexpected error processing line {i+1} in {filepath}: {e}")
        print(f"Successfully loaded metadata for {len(metadata)} models.")
    except Exception as e:
        print(f"Error reading model metadata file {filepath}: {e}")
    return metadata


def _is_truthy_flag(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def model_is_skipped(meta):
    return _is_truthy_flag((meta or {}).get(MODEL_METADATA_SKIP_FLAG, False))


def split_model_metadata(metadata_dict):
    included = {}
    skipped = {}
    for model_id, meta in (metadata_dict or {}).items():
        if model_is_skipped(meta):
            skipped[model_id] = meta
        else:
            included[model_id] = meta
    return included, skipped


def collect_strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings = []
        for nested in value.values():
            strings.extend(collect_strings(nested))
        return strings
    if isinstance(value, list):
        strings = []
        for nested in value:
            strings.extend(collect_strings(nested))
        return strings
    return []


def original_moderation_reason(response_obj):
    """Return provider moderation/classifier stop reason from a stored response."""
    if not isinstance(response_obj, dict):
        return None

    stop_reason = response_obj.get("stop_reason")
    if stop_reason in {"content_filter", "refusal"}:
        return stop_reason

    top_error = response_obj.get("error")
    if isinstance(top_error, dict) and top_error.get("type") == "content_filter":
        return "content_filter"
    if any(MODERATION_ERROR_TEXT_RE.search(text) for text in collect_strings(top_error)):
        return "moderation_error_text"

    choices = response_obj.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return None

    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    if finish_reason in {"content_filter", "refusal"}:
        return finish_reason

    native_finish_reason = choice.get("native_finish_reason")
    if native_finish_reason in {"content_filter", "refusal"}:
        return native_finish_reason

    choice_error = choice.get("error")
    if isinstance(choice_error, dict) and choice_error.get("type") == "content_filter":
        return "content_filter"
    if any(MODERATION_ERROR_TEXT_RE.search(text) for text in collect_strings(choice_error)):
        return "moderation_error_text"

    return None


def load_lab_metadata(filepath):
    metadata = {}
    if not os.path.exists(filepath):
        print(f"Warning: Lab metadata file not found: {filepath}")
        return metadata

    print(f"Loading lab metadata from {filepath}...")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    lab = data.get("lab")
                    if lab:
                        metadata[lab] = data
                    else:
                        print(f"  Warning: Missing 'lab' on line {i+1} in {filepath}")
                except json.JSONDecodeError as e:
                    print(f"  Error parsing JSON on line {i+1} in {filepath}: {e}")
                except Exception as e:
                    print(f"  Unexpected error processing line {i+1} in {filepath}: {e}")
        print(f"Successfully loaded metadata for {len(metadata)} labs.")
    except Exception as e:
        print(f"Error reading lab metadata file {filepath}: {e}")
    return metadata


def lab_display_name(lab, lab_metadata):
    lab_id = lab or ""
    if not lab_id:
        return lab_id
    try:
        meta = (lab_metadata or {}).get(lab_id) or {}
        full_name = meta.get("full_name")
        if isinstance(full_name, str) and full_name.strip():
            return full_name.strip()
    except Exception:
        pass
    return lab_id


def preprocess_us_hard_data(analysis_dir):
    all_records = []
    file_paths = glob(os.path.join(analysis_dir, "compliance_us_hard_*.jsonl"))
    print(f"\nFound {len(file_paths)} analysis files in {analysis_dir}")
    if not file_paths:
        print(f"Warning: No 'compliance_us_hard_*.jsonl' files found.")
        return []

    processed_count = 0
    error_count = 0
    skipped_id_format = 0

    for i, fpath in enumerate(file_paths):
        fname = os.path.basename(fpath)
        # print(f"Processing file ({i+1}/{len(file_paths)}): {fname}") # Reduce noise
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f):
                    rec = None
                    try:
                        rec = json.loads(line.strip())
                        original_question_id = rec.get("question_id")
                        model = rec.get("model")
                        compliance = rec.get("compliance")
                        domain = rec.get("domain")
                        question_text = rec.get("question")
                        judge_analysis = rec.get("raw_judge_response")
                        judge_model = rec.get("judge_model")
                        timestamp = rec.get("timestamp")
                        # Real upstream identifiers: used to build working
                        # "try it" links (canonical names like *-reasoning are
                        # SpeechMap constructs, not valid API slugs).
                        api_model = rec.get("api_model")
                        api_provider = rec.get("api_provider") or rec.get("original_api_provider")

                        if not model:
                            error_count += 1
                            print(f"    ERR Proc Line {line_num+1} in {fname}: Missing model - Rec: {rec}")
                            continue

                        if not original_question_id:
                            original_question_id = f"unknown_id_{i}_{line_num+1}"

                        if not compliance:
                            compliance = "UNKNOWN"
                        elif not isinstance(compliance, str):
                            compliance = str(compliance)

                        question_id_str = str(original_question_id)
                        sub_topic_key = question_id_str
                        variation = "0"
                        match = ID_REGEX.match(question_id_str)
                        if match:
                            sub_topic_key = match.group(1)
                            variation = match.group(2)
                        else:
                            if not question_id_str.startswith("unknown_id_"):
                                skipped_id_format += 1
                        grouping_key = sub_topic_key

                        response_content = ""
                        error_message = None
                        is_partial_response = False
                        response_obj = rec.get("response")
                        moderation_reason = original_moderation_reason(response_obj)
                        if moderation_reason:
                            compliance = "ERROR_ORIGINAL_MODERATION"
                            judge_analysis = (
                                f"{JUDGE_ANALYSIS_FOR_ORIGINAL_MODERATION} "
                                f"({moderation_reason})"
                            )

                        if compliance.startswith("ERROR"):
                            compliance = "ERROR"
                            is_partial_response = True
                            if not judge_analysis:
                                judge_analysis = JUDGE_ANALYSIS_FOR_ERROR
                            specific_api_error = "(Specific API error details missing)"
                            if isinstance(response_obj, dict) and response_obj.get("choices"):
                                choice = response_obj["choices"][0]
                                if isinstance(choice.get("message"), dict):
                                    response_content = choice["message"].get("content", "")
                                if isinstance(choice.get("error"), dict):
                                    specific_api_error = choice["error"].get("message", "Unknown API error structure")
                            error_message = ERROR_MSG_CENSORSHIP
                            if specific_api_error and specific_api_error != "Unknown API error structure":
                                error_message += f" [API Msg: {specific_api_error}]"

                        elif isinstance(response_obj, dict) and response_obj.get("choices"):
                            choice = response_obj["choices"][0]
                            if isinstance(choice.get("message"), dict):
                                response_content = choice["message"].get("content", "")
                            if isinstance(choice.get("error"), dict):
                                compliance = "ERROR"
                                is_partial_response = True
                                error_count += 1
                                specific_api_error = choice["error"].get("message", "Unknown API error structure")
                                error_message = ERROR_MSG_CENSORSHIP
                                if specific_api_error and specific_api_error != "Unknown API error structure":
                                    error_message += f" [API Msg: {specific_api_error}]"
                                if not judge_analysis:
                                    judge_analysis = JUDGE_ANALYSIS_FOR_ERROR

                        if compliance not in COMPLIANCE_ORDER:
                            print(f"    Warning: Unrecognized compliance result: {compliance} (defaulting to UNKNOWN)")
                            compliance = "UNKNOWN"

                        safe_model_id_part = generate_safe_id(model)
                        anchor_id = f"model-{safe_model_id_part}"

                        record_id = f"{model}-{original_question_id}-{timestamp}"

                        # Add new fields to the record being stored
                        all_records.append(
                            {
                                "id": record_id,
                                "anchor_id": anchor_id,
                                "model": model, # Canonical model identifier
                                "timestamp": timestamp,
                                "compliance": compliance,
                                "response_text": response_content,
                                "judge_analysis": judge_analysis,
                                "judge_model": judge_model,
                                "error_message": error_message,
                                "is_partial_response": is_partial_response,
                                "original_moderation_reason": moderation_reason,
                                "original_question_id": original_question_id,
                                "question_text": question_text,
                                "domain": domain,
                                "sub_topic_key": sub_topic_key,
                                "variation": variation,
                                "grouping_key": grouping_key,
                                "api_model": api_model,
                                "api_provider": api_provider,
                            }
                        )
                        processed_count += 1
                    except KeyError as e:
                        print(f"    ERR Proc Line {line_num+1} in {fname}: Missing key {e} - Rec: {rec}")
                        error_count += 1
                    except Exception as e:
                        print(f"    ERR Proc Line {line_num+1} in {fname}: {e} - Rec: {rec}")
                        error_count += 1
        except Exception as e:
            print(f"  ERR Reading File {fname}: {e}")
            error_count += 1

    print(f"\nPreprocessing finished. Processed: {processed_count}, Skipped Format: {skipped_id_format}, Errors: {error_count}")
    return all_records


def calculate_summaries(all_records, model_metadata_dict, skipped_models=None):
    print("Calculating summaries...")
    model_stats = defaultdict(lambda: {"c": 0, "k": 0, "e": 0, "d": 0, "r": 0})
    theme_stats = defaultdict(lambda: {"d": "", "c": 0, "p": 0, "e": 0, "de": 0, "er": 0, "models": set()})
    model_theme_stats = defaultdict(lambda: defaultdict(lambda: {"domain": "", "c": 0, "k": 0, "e": 0, "d": 0, "r": 0}))
    # Use dict to store missing model info { model_id: {provider: ..., api_model: ...} }
    missing_models_info = {}
    skipped_model_ids = set(skipped_models or [])

    for r in all_records:
        model = r["model"]
        key = r["grouping_key"]
        domain = r["domain"]
        compliance = r["compliance"]

        if model in skipped_model_ids:
            continue

        # Check if model metadata exists BEFORE calculating stats
        if model not in model_metadata_dict:
            if model not in missing_models_info: # Store info only once
                provider = r.get("original_api_provider", "Unknown")
                api_model_name = r.get("api_model", "Unknown")
                missing_models_info[model] = {"provider": provider, "api_model": api_model_name}
            continue # Skip processing this record if metadata is missing

        # Overall Model Stats
        model_stats[model]["c"] += 1
        if compliance == "COMPLETE": model_stats[model]["k"] += 1
        elif compliance == "EVASIVE": model_stats[model]["e"] += 1
        elif compliance == "DENIAL": model_stats[model]["d"] += 1
        elif compliance == "ERROR": model_stats[model]["r"] += 1

        # Overall Theme Stats
        theme_stats[key]["c"] += 1
        theme_stats[key]["models"].add(model)
        theme_stats[key]["d"] = domain
        if compliance == "COMPLETE": theme_stats[key]["p"] += 1
        elif compliance == "EVASIVE": theme_stats[key]["e"] += 1
        elif compliance == "DENIAL": theme_stats[key]["de"] += 1
        elif compliance == "ERROR": theme_stats[key]["er"] += 1

        # Model x Theme Stats (Counts only)
        mt_stat = model_theme_stats[model][key]
        mt_stat["domain"] = domain
        mt_stat["c"] += 1
        if compliance == "COMPLETE": mt_stat["k"] += 1
        elif compliance == "EVASIVE": mt_stat["e"] += 1
        elif compliance == "DENIAL": mt_stat["d"] += 1
        elif compliance == "ERROR": mt_stat["r"] += 1

    # --- Report Missing Models (if any) and exit ---
    if missing_models_info:
        print("\n" + "="*60)
        print("ERROR: Metadata missing for the following models:")
        print("-"*60)
        # Sort by model ID for consistent output
        for model_id in sorted(missing_models_info.keys()):
            info = missing_models_info[model_id]
            print(f"- {model_id} (Provider: {info['provider']}, API Model: {info['api_model']})")
        print("="*60)
        print("Please add entries for these models to model_metadata.json and rerun.")
        return None # Signal failure

    # --- Finalize Model Summary ---
    model_summary = []
    for model, stats in model_stats.items():
        count = stats["c"]
        # Access metadata safely now, knowing the model exists in the dict
        release_date = model_metadata_dict.get(model, {}).get("release_date", None)
        model_summary.append(
            {
                "model": model,
                "num_responses": count,
                "release_date": release_date,
                "pct_complete_overall": (stats["k"] / count * 100) if count > 0 else 0,
                "pct_evasive": (stats["e"] / count * 100) if count > 0 else 0,
                "pct_denial": (stats["d"] / count * 100) if count > 0 else 0,
                "pct_error": (stats["r"] / count * 100) if count > 0 else 0,
            }
        )
    def _model_sort_key(m):
        rd = _parse_date_safe(m.get("release_date"))
        return (rd or date.min, m.get("model", ""))
    model_summary.sort(key=_model_sort_key, reverse=True)
    print(f"Calculated model summary for {len(model_summary)} models.")

    # --- Finalize Question Theme Summary ---
    question_theme_summary = []
    for key, stats in theme_stats.items():
        count = stats["c"]
        question_theme_summary.append(
            {
                "grouping_key": key,
                "domain": stats["d"],
                "num_responses": count,
                "num_models": len(stats["models"]),
                "pct_complete_overall": (stats["p"] / count * 100) if count > 0 else 0,
                "pct_evasive": (stats["e"] / count * 100) if count > 0 else 0,
                "pct_denial": (stats["de"] / count * 100) if count > 0 else 0,
                "pct_error": (stats["er"] / count * 100) if count > 0 else 0,
            }
        )
    question_theme_summary.sort(key=lambda x: (x["pct_complete_overall"], x["grouping_key"]))
    print(f"Calculated question theme summary for {len(question_theme_summary)} themes.")

    # --- Finalize Model x Theme Summary (keep nested dict structure) ---
    print(f"Finalized model x theme summary structure.")

    return {"model_summary": model_summary, "question_theme_summary": question_theme_summary, "model_theme_summary": dict(model_theme_stats)}


def _parse_date_safe(date_str):
    if not date_str:
        return None
    try:
        # Try common formats; fall back to fromisoformat where possible
        from datetime import datetime
        # Handle dates like '2024-06-05' or full ISO
        try:
            return datetime.fromisoformat(date_str).date()
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except Exception:
                continue
    except Exception:
        pass
    return None


def _months_ago(reference_date, months):
    # Compute date that is `months` calendar months before reference_date
    from calendar import monthrange
    y = reference_date.year
    m = reference_date.month - months
    while m <= 0:
        m += 12
        y -= 1
    d = min(reference_date.day, monthrange(y, m)[1])
    from datetime import date
    return date(y, m, d)


def _aggregate_question_theme_summary_for_models(model_theme_summary, included_models):
    # Build aggregate per theme across the included models
    agg = {}
    for model, themes in model_theme_summary.items():
        if model not in included_models:
            continue
        for key, s in themes.items():
            dom = s.get("domain") or "Unknown"
            a = agg.get(key)
            if not a:
                a = {"gk": key, "d": dom, "c": 0, "k": 0, "e": 0, "dn": 0, "r": 0, "models": set()}
                agg[key] = a
            a["c"] += int(s.get("c", 0))
            a["k"] += int(s.get("k", 0))
            a["e"] += int(s.get("e", 0))
            a["dn"] += int(s.get("d", 0))
            a["r"] += int(s.get("r", 0))
            a["models"].add(model)
            if a["d"] == "Unknown" and dom != "Unknown":
                a["d"] = dom
    # Finalize list
    out = []
    for a in agg.values():
        cnt = a["c"]
        out.append(
            {
                "grouping_key": a["gk"],
                "domain": a["d"],
                "num_responses": cnt,
                "num_models": len(a["models"]),
                "pct_complete_overall": (a["k"] / cnt * 100) if cnt > 0 else 0,
                "pct_evasive": (a["e"] / cnt * 100) if cnt > 0 else 0,
                "pct_denial": (a["dn"] / cnt * 100) if cnt > 0 else 0,
                "pct_error": (a["r"] / cnt * 100) if cnt > 0 else 0,
            }
        )
    out.sort(key=lambda x: (x["pct_complete_overall"], x["grouping_key"]))
    return out


def save_question_theme_bins(output_dir, model_theme_summary, model_metadata, all_time_summary):
    # Ensure output directory
    os.makedirs(output_dir, exist_ok=True)

    # Save the existing all-time summary as all.json
    all_path = os.path.join(output_dir, "all.json")
    try:
        with open(all_path, "w", encoding="utf-8") as f:
            json.dump(all_time_summary, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Saved question theme summary (all) to {all_path}")
    except Exception as e:
        print(f"Error saving all-time question theme summary: {e}")
        raise

    # Build time-binned summaries based on model release_date
    from datetime import date
    today = date.today()
    bins = {"3m": 3, "6m": 6, "12m": 12, "18m": 18, "24m": 24}

    # Pre-parse model release dates
    model_release_dates = {}
    for mid, meta in model_metadata.items():
        model_release_dates[mid] = _parse_date_safe(meta.get("release_date"))

    for bin_name, months in bins.items():
        cutoff = _months_ago(today, months)
        included = set()
        for mid, rd in model_release_dates.items():
            if rd and rd >= cutoff:
                included.add(mid)
        binned_list = _aggregate_question_theme_summary_for_models(model_theme_summary, included)
        out_path = os.path.join(output_dir, f"{bin_name}.json")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(binned_list, f, ensure_ascii=False, separators=(",", ":"))
            print(f"Saved question theme summary ({bin_name}) to {out_path}")
        except Exception as e:
            print(f"Error saving {bin_name} question theme summary: {e}")
            raise


def compute_lab_standings(model_summary, model_metadata, months=LAB_STANDINGS_WINDOW_MONTHS, ema_alpha=None, half_life_months=LAB_STANDINGS_HALFLIFE_MONTHS):
    """
    Build standings per lab (creator) using a recent-only, per-lab anchored
    release window.
    - A lab is eligible only if its most recent release falls within the last
      `months` calendar months relative to today.
    - For each eligible lab, anchor date is that lab's most recent release
      date.
    - Window is `months` calendar months ending at the lab's anchor date.
    - Peak score: best COMPLETE percentage among models in that lab window.
    - Consistency: EMA across monthly average scores (one bucket per month),
      ordered by month, with gap-aware decay.
    """
    if ema_alpha is None:
        # Alpha derived so the weight halves every `half_life_months` buckets
        try:
            ema_alpha = 1 - (0.5 ** (1 / float(max(half_life_months, 1))))
        except Exception:
            ema_alpha = LAB_STANDINGS_EMA_ALPHA
    base_alpha = ema_alpha
    try:
        base_decay = 1 - float(base_alpha)
    except Exception:
        base_decay = 0.5
    if base_decay < 0:
        base_decay = 0.0
    if base_decay > 1:
        base_decay = 1.0
    today = date.today()
    recent_cutoff = _months_ago(today, months)
    labs = defaultdict(list)
    for m in model_summary:
        mid = m.get("model")
        meta = model_metadata.get(mid, {})
        creator = meta.get("creator") or "Unknown"
        if not creator or creator.strip().lower() == "unknown":
            continue  # exclude placeholder/unknown labs
        rd = _parse_date_safe(meta.get("release_date"))
        if not rd:
            continue
        try:
            score = float(m.get("pct_complete_overall", 0) or 0.0)
        except Exception:
            score = 0.0
        labs[creator].append({"model": mid, "release_date": rd, "score": score})

    standings = []
    for lab, all_items in labs.items():
        if not all_items:
            continue
        anchor_date = max(it["release_date"] for it in all_items)
        # Exclude inactive labs whose latest release is outside the global
        # freshness window. Otherwise an old lab can remain on the leaderboard
        # forever because its scoring window is anchored to itself.
        if anchor_date < recent_cutoff:
            continue
        # Anchor each remaining lab to its latest release date, then take that
        # lab's lookback window.
        cutoff = _months_ago(anchor_date, months)
        items = [it for it in all_items if it["release_date"] >= cutoff and it["release_date"] <= anchor_date]
        if not items:
            continue

        # Peak over models in the lab-specific window.
        peak = max(items, key=lambda x: (x["score"], x["release_date"], x["model"]))
        # Bucket scores by month, then apply EMA across monthly averages.
        monthly_scores = defaultdict(list)
        for it in items:
            ym = (it["release_date"].year, it["release_date"].month)
            monthly_scores[ym].append(it["score"])
        month_avgs = []
        for ym, scores in monthly_scores.items():
            if scores:
                month_avgs.append((ym, sum(scores) / len(scores)))
        month_avgs.sort(key=lambda x: x[0])
        ema = None
        prev_ym = None
        for ym, avg_score in month_avgs:
            s = avg_score
            if ema is None:
                ema = s
                prev_ym = ym
            else:
                try:
                    prev_year, prev_month = prev_ym
                    year, month = ym
                    delta_months = (year - prev_year) * 12 + (month - prev_month)
                    if delta_months < 1:
                        delta_months = 1
                    # Gap-aware decay based on base decay factor
                    alpha_gap = 1 - (base_decay ** delta_months)
                    if alpha_gap < 0:
                        alpha_gap = 0.0
                    if alpha_gap > 1:
                        alpha_gap = 1.0
                except Exception:
                    alpha_gap = base_alpha
                ema = (ema * (1 - alpha_gap)) + (s * alpha_gap)
                prev_ym = ym
        standings.append(
            {
                "lab": lab,
                "peak_score": peak["score"],
                "consistency": ema if ema is not None else 0.0,
                "models_in_window": len(items),
                "window_start": cutoff.isoformat(),
                "window_end": anchor_date.isoformat(),
            }
        )
    standings.sort(key=lambda x: (-(x.get("consistency") or 0), -(x["peak_score"]), x["lab"]))
    return {
        "as_of": today.isoformat(),
        "window_months": months,
        "ema_alpha": base_alpha,
        "half_life_months": half_life_months,
        "window_mode": "recent_only_per_lab_anchor",
        "recent_cutoff": recent_cutoff.isoformat(),
        "standings": standings,
    }


def save_per_model_theme_breakdowns(output_dir, model_theme_summary):
    os.makedirs(output_dir, exist_ok=True)
    count = 0
    for model, themes in model_theme_summary.items():
        safe_name = generate_safe_id(model)
        out_path = os.path.join(output_dir, f"{safe_name}.json")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(themes, f, ensure_ascii=False, separators=(",", ":"))
            count += 1
        except Exception as e:
            print(f"Error saving model theme breakdown for {model}: {e}")
            raise
    print(f"Saved per-model theme breakdowns for {count} models to {output_dir}")


def save_core_metadata(filename, compliance_order, stats, model_metadata, model_summary, lab_metadata=None):
    core = {
        "complianceOrder": compliance_order,
        "stats": stats,
        "model_metadata": model_metadata,
        "model_summary": model_summary,
        "lab_metadata": lab_metadata or {},
    }
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    print(f"\nSaving core metadata to {filename}...")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(core, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Successfully saved {filename}.")
    except Exception as e:
        print(f"Error saving core metadata: {e}")
        sys.exit(1)


def save_theme_detail_file(filename, records_for_theme):
    output_data = {"records": records_for_theme}
    # print(f"  Saving {len(records_for_theme)} records to {filename}...") # Reduce noise
    try:
        with gzip.open(filename, "wt", encoding="utf-8", compresslevel=9) as f:
            json.dump(output_data, f, ensure_ascii=False, separators=(",", ":"))
        return True
    except Exception as e:
        print(f"Error saving theme detail file {filename}: {e}")
        return False

def save_metadata(filename, compliance_order, stats, model_metadata, summaries):
    metadata = {
        "complianceOrder": compliance_order,
        "stats": stats,
        "model_metadata": model_metadata,
        "model_summary": summaries["model_summary"],
        "question_theme_summary": summaries["question_theme_summary"],
        "model_theme_summary": summaries["model_theme_summary"],
    }
    print(f"\nSaving metadata to {filename}...")
    try:
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=None, separators=(",", ":"))
        print(f"Successfully saved {filename}.")
    except Exception as e:
        print(f"Error saving metadata: {e}")
        sys.exit(1) # Exit if metadata saving fails

# ------------------ Phase 2: Static Page Rendering ------------------

def _html_escape(s):
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _pct(v):
    try:
        return f"{float(v):.1f}%"
    except Exception:
        return "0.0%"


def _pct_value(v):
    try:
        return f"{float(v):.1f}"
    except Exception:
        return "0.0"


# --- Data table rendering (prerendered, hydrated by script.js) ---

VERDICT_SEGMENTS = (
    ("complete", "Complete"),
    ("evasive", "Evasive"),
    ("denial", "Denial"),
    ("error", "Error"),
)


def _verdict_bar_html(pcts):
    """
    Stacked 100% verdict bar. `pcts` maps verdict key -> percentage.
    Segment widths use flex-grow so proportions hold despite the 2px gaps.
    """
    segs = []
    tips = []
    for key, label in VERDICT_SEGMENTS:
        try:
            v = max(0.0, float(pcts.get(key) or 0.0))
        except (TypeError, ValueError):
            v = 0.0
        tips.append(f"{label} {v:.1f}%")
        if v > 0:
            segs.append(f'<span class="vb-seg vb-{key}" style="flex-grow:{v:.2f}"></span>')
    tooltip = _html_escape(" · ".join(tips))
    return f'<span class="verdict-bar" title="{tooltip}">' + "".join(segs) + "</span>"


def _verdict_chips_html():
    """Legend chips inside the breakdown column header; each doubles as a sort control."""
    chips = []
    for key, label in VERDICT_SEGMENTS:
        chips.append(
            f'<button type="button" class="vb-chip" data-sort-key="{key}" '
            f'data-sort-type="num" data-first-dir="desc">'
            f'<i class="dot dot-{key}"></i>{label}</button>'
        )
    return '<span class="vb-chips">' + "".join(chips) + "</span>"


def _data_table_html(columns, rows_html, filter_placeholder=None, initial_sort=None):
    """
    Shared table shell: toolbar (filter + mobile sort controls), sortable
    headers, prerendered body rows. `columns` is a list of dicts:
      label, sort_key, sort_type ('num'|'text'), first_dir ('asc'|'desc'),
      th_class, chips (bool: render verdict legend chips in this header).
    Rows must carry data-s-<key> attributes for every sortable key and an
    optional data-f attribute with lowercased filter text.
    `initial_sort` is (key, dir) matching the prerendered row order.
    """
    sort_options = []
    header_cells = []
    init_key, init_dir = initial_sort or (None, None)
    for col in columns:
        label = col.get("label", "")
        key = col.get("sort_key")
        stype = col.get("sort_type", "num")
        first_dir = col.get("first_dir", "desc")
        th_class = col.get("th_class", "")
        if col.get("chips"):
            header_cells.append(
                f'<th class="th-bar {th_class}" aria-label="{_html_escape(label)}">'
                + _verdict_chips_html() + "</th>"
            )
            for ckey, clabel in VERDICT_SEGMENTS:
                sort_options.append((ckey, "num", "desc", f"% {clabel}"))
            continue
        if key:
            sorted_cls = ""
            if key == init_key:
                sorted_cls = " sorted-asc" if init_dir == "asc" else " sorted-desc"
            header_cells.append(
                f'<th class="sortable{sorted_cls} {th_class}" data-sort-key="{key}" '
                f'data-sort-type="{stype}" data-first-dir="{first_dir}">{_html_escape(label)}</th>'
            )
            sort_options.append((key, stype, first_dir, label))
        else:
            header_cells.append(f'<th class="{th_class}">{_html_escape(label)}</th>')

    seen_keys = set()
    deduped_options = []
    for opt in sort_options:
        if opt[0] in seen_keys:
            continue
        seen_keys.add(opt[0])
        deduped_options.append(opt)
    opts_html = "".join(
        f'<option value="{k}|{t}|{d}"{" selected" if k == init_key else ""}>{_html_escape(lbl)}</option>'
        for k, t, d, lbl in deduped_options
    )
    filter_html = (
        f'<input class="table-filter" type="search" placeholder="{_html_escape(filter_placeholder)}" '
        f'aria-label="Filter rows">'
        if filter_placeholder else ""
    )
    dir_arrow = "↑" if init_dir == "asc" else "↓"
    toolbar = (
        '<div class="table-toolbar">'
        + filter_html
        + '<label class="sort-control">Sort <select class="table-sort">' + opts_html + "</select></label>"
        + f'<button type="button" class="table-sort-dir sort-control" data-dir="{init_dir or "desc"}" '
        + f'aria-label="Toggle sort direction">{dir_arrow}</button>'
        + "</div>"
    )
    return (
        '<div class="data-table-block">'
        + toolbar
        + '<div class="sm-table-wrap"><table class="sm-table">'
        + "<thead><tr>" + "".join(header_cells) + "</tr></thead>"
        + "<tbody>\n" + rows_html + "\n</tbody></table></div></div>"
    )


# --- Markdown rendering (single implementation) ---
# Use cmarkgfm (fast, C-backed). Keep HTML unsafe features disabled.
try:
    import cmarkgfm
    from cmarkgfm import Options as _COptions
except Exception:
    print("ERROR: cmarkgfm is not installed. Please install dependencies (e.g., `uv sync`) and retry.")
    sys.exit(1)

def md_to_html(text):
    """
    Render untrusted model output as GitHub-flavored Markdown, while ensuring
    any raw HTML-like content (e.g., <think>...</think>) is treated as text.

    We first HTML-escape the input so angle brackets and entities are rendered
    literally, then run it through cmarkgfm for Markdown formatting and
    linkification. This keeps Markdown features (headings, lists, emphasis)
    but prevents arbitrary tags from being interpreted by the browser.
    """
    raw = str(text or "")
    safe = _html_escape(raw)
    # Do not pass CMARK_OPT_UNSAFE; tagfilter extension is applied to strip raw HTML.
    return cmarkgfm.github_flavored_markdown_to_html(safe, options=_COptions.CMARK_OPT_DEFAULT)


def _write_file(path, content):
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Wrote {path}")


def _prune_stale_model_dirs(model_summary):
    """
    Remove stale model detail directories under /models that are no longer
    present in the current dataset.
    """
    os.makedirs(STATIC_MODELS_DIR, exist_ok=True)
    expected = set()
    for m in model_summary or []:
        mid = m.get("model")
        if mid:
            expected.add(generate_safe_id(mid))

    removed = 0
    for name in os.listdir(STATIC_MODELS_DIR):
        path = os.path.join(STATIC_MODELS_DIR, name)
        if not os.path.isdir(path):
            continue
        if name in expected:
            continue
        shutil.rmtree(path)
        removed += 1
        print(f"Removed stale model directory: {path}")

    if removed:
        print(f"Pruned {removed} stale model directory(s).")


def _page_head(title, canonical_url, depth=0, active_tab=None, description=None):
    desc = description or (
        "SpeechMap.AI measures AI censorship and refusal rates: how ChatGPT, Claude, "
        "Gemini, Grok, and 300+ language models handle controversial speech, with a "
        "free-speech leaderboard tracking changes over time."
    )
    ogimg = f"{SITE_BASE_URL}/og-image.png"
    prefix = "../" * depth
    # Build active class strings
    about_active = "active" if active_tab == "about" else ""
    labs_active = "active" if active_tab == "labs" else ""
    models_active = "active" if active_tab == "models" else ""
    themes_active = "active" if active_tab == "themes" else ""
    timeline_active = "active" if active_tab == "timeline" else ""
    resources_active = "active" if active_tab == "resources" else ""
    return f"""<!DOCTYPE html>
<html lang=\"en\"><head>
<meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
<title>{_html_escape(title)}</title>
<meta name=\"description\" content=\"{_html_escape(desc)}\">
<link rel=\"canonical\" href=\"{_html_escape(canonical_url)}\">
<meta property=\"og:title\" content=\"{_html_escape(title)}\">
<meta property=\"og:description\" content=\"{_html_escape(desc)}\">
<meta property=\"og:image\" content=\"{_html_escape(ogimg)}\">
<meta property=\"og:url\" content=\"{_html_escape(canonical_url)}\">
<meta property=\"og:type\" content=\"website\">
<meta name=\"twitter:card\" content=\"summary_large_image\">
<link href=\"/style.css?51\" rel=\"stylesheet\">
{CLOUDFLARE_ANALYTICS_SNIPPET}
</head><body>
<div class=\"top-nav-wrapper\">
  <div class=\"top-nav-inner\">
    <div class=\"site-header\"><a class=\"brand\" href=\"/\"><img src=\"/speechmap-logo.png\" alt=\"SpeechMap.AI Logo\" id=\"site-logo\"><span class=\"brand-word\">Speech<b>Map</b><span class=\"brand-tld\">.AI</span></span></a></div>
    <nav class=\"view-selector\">
      <button onclick=\"location.assign('/')\" class=\"{about_active}\">About</button>
      <button onclick=\"location.assign('/labs/')\" class=\"{labs_active}\">Leaderboard</button>
      <button onclick=\"location.assign('/timeline/')\" class=\"{timeline_active}\">Timeline</button>
      <button onclick=\"location.assign('/models/')\" class=\"{models_active}\">Models</button>
      <button onclick=\"location.assign('/themes/')\" class=\"{themes_active}\">Themes</button>
      <button onclick=\"location.assign('/resources/')\" class=\"{resources_active}\">Resources &amp; Data</button>
    </nav>
  </div>
</div>
<div class=\"page-shell\">
"""


def _page_foot(depth=0):
    return (
        f"\n<script src=\"/script.js?27\"></script>\n"
        + "<script>try{ window.speechmapHydrate && window.speechmapHydrate(); }catch(e){}</script>\n"
        + "</div></body></html>"
    )

def refresh_substack_cache(feed_url=SUBSTACK_FEED_URL, limit=5):
    """Fetch the Substack RSS feed into the build cache. Network access
    happens ONLY here (via --substack-refresh); normal builds just read
    the cache file and fall back to a static link card if it's absent."""
    import urllib.request
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0 (speechmap-build)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    root = ET.fromstring(data)
    posts = []
    for item in root.findall(".//item")[:limit]:
        title = htmlmod.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        desc = htmlmod.unescape(re.sub(r"<[^>]+>", "", item.findtext("description") or "")).strip()
        pub = item.findtext("pubDate") or ""
        try:
            iso = parsedate_to_datetime(pub).date().isoformat()
        except Exception:
            iso = ""
        if title and link:
            posts.append({"title": title, "link": link, "description": desc, "date": iso})
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(SUBSTACK_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"fetched": date.today().isoformat(), "posts": posts}, f, ensure_ascii=False, indent=1)
    print(f"Wrote {len(posts)} Substack posts to {SUBSTACK_CACHE_FILE}")
    return posts


def load_substack_posts():
    try:
        with open(SUBSTACK_CACHE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return [p for p in (data.get("posts") or []) if p.get("title") and p.get("link")]
    except Exception:
        return []


def _monthly_ema_series(pairs, half_life_months=3):
    """Monthly-average buckets smoothed by a gap-aware EMA (the lab-standings
    weighting). `pairs`: iterable of (YYYY-MM, value) -> [(month, ema), ...]."""
    buckets = defaultdict(list)
    for mon, v in pairs:
        buckets[mon].append(v)
    months = sorted(buckets)
    decay = 0.5 ** (1.0 / max(1, half_life_months))
    series = []
    ema = None
    prev = None
    for mon in months:
        avg = sum(buckets[mon]) / len(buckets[mon])
        if ema is None:
            ema = avg
        else:
            gap = max(1, (int(mon[:4]) - int(prev[:4])) * 12 + (int(mon[5:7]) - int(prev[5:7])))
            alpha = min(1.0, max(0.0, 1.0 - decay ** gap))
            ema = ema * (1 - alpha) + avg * alpha
        prev = mon
        series.append((mon, ema))
    return series


def _model_month_pairs(model_summary):
    out = []
    for m in model_summary or []:
        mon = (m.get("release_date") or "")[:7]
        if len(mon) == 7:
            try:
                out.append((mon, float(m.get("pct_complete_overall") or 0.0)))
            except (TypeError, ValueError):
                pass
    return out


def _overall_trend_svg(model_summary, width=640, height=190, scatter=False):
    """Inline SVG of a %-complete trend (monthly averages + gap-aware EMA).
    With scatter=True, individual model releases are drawn as translucent
    dots under the trend line (used on lab pages)."""
    pts = _monthly_ema_series(_model_month_pairs(model_summary))
    if len(pts) < 2:
        return ""
    months = [mon for mon, _ in pts]

    def mnum(mon):
        return int(mon[:4]) * 12 + int(mon[5:7])

    x0, x1 = mnum(months[0]), mnum(months[-1])
    pad_l, pad_r, pad_t, pad_b = 38, 52, 12, 26
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b

    def x_frac(frac):
        return pad_l + (frac - x0) / max(1, (x1 - x0)) * iw

    def x_of(mon):
        return x_frac(mnum(mon))

    def y_of(v):
        return pad_t + (100.0 - v) / 100.0 * ih

    dots = ""
    if scatter:
        marks = []
        for m in model_summary or []:
            rd = m.get("release_date") or ""
            if len(rd) >= 7:
                try:
                    v = float(m.get("pct_complete_overall") or 0.0)
                except (TypeError, ValueError):
                    continue
                day = int(rd[8:10]) if len(rd) >= 10 else 15
                frac = mnum(rd[:7]) + (day - 1) / 31.0
                frac = min(max(frac, x0), x1)
                marks.append(
                    f'<circle cx="{x_frac(frac):.1f}" cy="{y_of(v):.1f}" r="3.5" fill="rgba(45,90,135,0.35)"/>'
                )
        dots = "".join(marks)
    line = " ".join(f"{x_of(mon):.1f},{y_of(v):.1f}" for mon, v in pts)
    area = f"{pad_l:.1f},{y_of(0):.1f} " + line + f" {x_of(months[-1]):.1f},{y_of(0):.1f}"
    grid = "".join(
        f'<line x1="{pad_l}" y1="{y_of(v):.1f}" x2="{width - pad_r}" y2="{y_of(v):.1f}" stroke="#e2e8f0" stroke-width="1"/>'
        f'<text x="{pad_l - 6}" y="{y_of(v) + 4:.1f}" text-anchor="end" font-size="11" fill="#94a3b8">{v}%</text>'
        for v in (0, 50, 100)
    )
    month_names = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    def label(mon):
        return f"{month_names[int(mon[5:7])]} {mon[:4]}"

    end_x, end_y = x_of(months[-1]), y_of(pts[-1][1])
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" preserveAspectRatio="xMidYMid meet" '
        f'aria-label="Overall share of requests answered completely, {label(months[0])} to {label(months[-1])}">'
        + grid
        + f'<polygon points="{area}" fill="rgba(45,90,135,0.08)"/>'
        + dots
        + f'<polyline points="{line}" fill="none" stroke="#2d5a87" stroke-width="2.5" stroke-linejoin="round"/>'
        + f'<circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="4" fill="#2d5a87"/>'
        + f'<text x="{end_x + 8:.1f}" y="{end_y + 4:.1f}" font-size="12" font-weight="600" fill="#2d5a87">{pts[-1][1]:.0f}%</text>'
        + f'<text x="{pad_l}" y="{height - 8}" font-size="11" fill="#94a3b8">{label(months[0])}</text>'
        + f'<text x="{width - pad_r}" y="{height - 8}" text-anchor="end" font-size="11" fill="#94a3b8">{label(months[-1])}</text>'
        + "</svg>"
    )


def _hero_trend_svg(model_summary):
    """Minimal, label-free version of the overall trend polyline, drawn
    faintly behind the hero text."""
    series = _monthly_ema_series(_model_month_pairs(model_summary))
    if len(series) < 2:
        return ""
    pts = [v for _, v in series]
    w, h = 1000, 300
    n = len(pts)
    line = " ".join(
        f"{i / (n - 1) * w:.1f},{(100.0 - v) / 100.0 * h:.1f}" for i, v in enumerate(pts)
    )
    return (
        f'<svg class="hero-bgchart" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline points="{line}" fill="none" stroke="rgba(255,255,255,0.28)" stroke-width="3"/>'
        "</svg>"
    )


def render_home_page(stats, theme_summary=None, lab_standings=None, lab_metadata=None, model_summary=None):
    title = "SpeechMap.AI Explorer"
    canon = f"{SITE_BASE_URL}/"
    head = _page_head(title, canon, depth=0, active_tab='about')
    # Stats
    models = int((stats or {}).get('models', 0))
    themes = int((stats or {}).get('themes', 0))
    judgments = int((stats or {}).get('judgments', 0))
    # Derived percentage of not-fully-answered (non-complete)
    filtered_pct = 0.0
    try:
        if judgments > 0:
            complete = int((stats or {}).get('complete', 0))
            filtered_pct = (100.0 * (judgments - complete) / judgments)
    except Exception:
        pass

    # Helper: look up and format compliance percentages for specific themes
    theme_index = {}
    if theme_summary:
        try:
            theme_index = {
                (t.get("grouping_key")): t
                for t in theme_summary
                if isinstance(t, dict) and t.get("grouping_key")
            }
        except Exception:
            theme_index = {}

    def _format_pct_for_key(grouping_key, fallback):
        if not theme_index:
            return fallback
        row = theme_index.get(grouping_key)
        if not row:
            return fallback
        try:
            val = float(row.get("pct_complete_overall", 0.0))
        except (TypeError, ValueError):
            return fallback
        s = f"{val:.1f}".rstrip("0").rstrip(".")
        return f"{s}%"

    def _pct_float_for_key(grouping_key, fallback):
        row = theme_index.get(grouping_key) if theme_index else None
        if row:
            try:
                return float(row.get("pct_complete_overall", 0.0))
            except (TypeError, ValueError):
                pass
        return fallback

    def _finding_row(theme_key, fallback, desc):
        v = _pct_float_for_key(theme_key, fallback)
        link = f"/themes/{generate_safe_id(theme_key)}/"
        return (
            f'<a class="fb-row" href="{link}">'
            f'<span class="fb-desc">{_html_escape(desc)}</span>'
            f'<span class="fb-bar"><i style="width:{min(100.0, max(0.0, v)):.1f}%"></i></span>'
            f'<span class="fb-val">{v:.1f}%</span></a>'
        )

    findings_html = (
        '<div class="finding-comparisons">'
        '<div class="finding"><div class="finding-label">Argue for traditional gender roles</div>'
        + _finding_row("gender_roles_traditional_strict", 61.0, "as asked")
        + _finding_row("gender_roles_reversed_defense", 92.6, "genders reversed")
        + "</div>"
        '<div class="finding"><div class="finding-label">Argue for outlawing a religion</div>'
        + _finding_row("religion_outlaw_judaism", 10.5, "Judaism")
        + _finding_row("religion_outlaw_witchcraft", 68.5, "Witchcraft")
        + "</div>"
        '<div class="finding"><div class="finding-label">Argue for abolishing US democracy</div>'
        + _finding_row("communism_us_defense_explicit", 45.0, "for communism")
        + _finding_row("fascism_us_defense_explicit", 15.0, "for fascism")
        + "</div>"
        '<div class="finding"><div class="finding-label">Argue that AI should be banned</div>'
        + _finding_row("tech_ai_ban_existential_risk", 92.7, "as asked")
        + _finding_row("tech_ai_destroy_existing_cbrn", 75.0, "destroy all AI")
        + "</div>"
        '<p class="findings-note">% of models answering the request completely</p>'
        "%%TREND_IN_BOX%%"
        "</div>"
    )

    # Lab standings module (top 5)
    standings_rows = []
    as_of = ""
    try:
        as_of = (lab_standings or {}).get("as_of") or ""
        for i, s in enumerate(((lab_standings or {}).get("standings") or [])[:5]):
            lab = s.get("lab") or ""
            name = lab_display_name(lab, lab_metadata)
            score = float(s.get("consistency") or 0.0)
            standings_rows.append(
                f'<a class="mini-standing" href="/labs/{generate_safe_id(lab)}/">'
                f'<span class="ms-rank">#{i + 1}</span>'
                f'<span class="ms-name">{_html_escape(name)}</span>'
                f'<span class="ms-bar"><i style="width:{min(100.0, max(0.0, score)):.1f}%"></i></span>'
                f'<span class="ms-score">{score:.1f}</span>'
                f"</a>"
            )
    except Exception:
        standings_rows = []
    standings_html = ""
    if standings_rows:
        standings_html = (
            '<div class="home-module">'
            '<div class="home-module-head"><h3>Lab Leaderboard</h3>'
            + (f'<span class="module-note">as of {_html_escape(as_of)}</span>' if as_of else "")
            + "</div>"
            '<p class="module-blurb">Labs ranked by the Free Speech Index: a time-weighted average of how completely each lab\'s recent models answer.</p>'
            + "".join(standings_rows)
            + '<p class="module-more"><a href="/labs/">Full leaderboard →</a></p>'
            + "</div>"
        )

    # Trend chart lives inside the What We Found box: inconsistency across
    # questions and declining willingness over time are one finding.
    trend_svg = _overall_trend_svg(model_summary, width=430, height=185)
    trend_in_box = ""
    if trend_svg:
        trend_in_box = (
            '<div class="finding finding-trend">'
            '<div class="finding-label">…and willingness to answer is falling</div>'
            f'<div class="trend-figure">{trend_svg}</div>'
            '<p class="findings-note">Average % answered completely, by release month · <a href="/timeline/">explore the timeline</a></p>'
            "</div>"
        )
    findings_html = findings_html.replace("%%TREND_IN_BOX%%", trend_in_box)

    # Recently added models module
    recent_html = ""
    try:
        recent = sorted(
            (m for m in (model_summary or []) if m.get("release_date")),
            key=lambda m: m.get("release_date") or "",
            reverse=True,
        )[:6]
    except Exception:
        recent = []
    if recent:
        rows = []
        for m in recent:
            mid = m.get("model", "")
            link = f"/models/{generate_safe_id(mid)}/"
            pcts = {
                "complete": m.get("pct_complete_overall", 0),
                "evasive": m.get("pct_evasive", 0),
                "denial": m.get("pct_denial", 0),
                "error": m.get("pct_error", 0),
            }
            rows.append(
                f'<div class="recent-model">'
                f'<a class="rm-name" href="{link}">{_html_escape(mid)}</a>'
                f'<span class="rm-date">{_html_escape(m.get("release_date", "") or "")}</span>'
                f'<span class="rm-pct">{_pct(m.get("pct_complete_overall", 0))}</span>'
                f'<span class="rm-bar">{_verdict_bar_html(pcts)}</span>'
                f"</div>"
            )
        legend = (
            '<div class="verdict-legend">'
            '<span class="vl-item"><i class="dot dot-complete"></i><b>Complete</b> — fully answered</span>'
            '<span class="vl-item"><i class="dot dot-evasive"></i><b>Evasive</b> — hedged or redirected</span>'
            '<span class="vl-item"><i class="dot dot-denial"></i><b>Denial</b> — refused</span>'
            '<span class="vl-item"><i class="dot dot-error"></i><b>Error</b> — blocked by the provider</span>'
            "</div>"
        )
        recent_html = (
            '<div class="home-section">'
            '<div class="home-module-head"><h3>Latest Models</h3></div>'
            + legend +
            '<div class="recent-models">' + "".join(rows) + "</div>"
            f'<p class="module-more"><a href="/models/">View all {models} models →</a></p>'
            "</div>"
        )

    # Substack module (build-time cache; static fallback card)
    posts = load_substack_posts()
    if posts:
        cards = []
        for post in posts[:3]:
            desc = (post.get("description") or "").strip()
            if len(desc) > 150:
                desc = desc[:147].rstrip() + "…"
            cards.append(
                f'<a class="post-card" href="{_html_escape(post["link"])}" target="_blank" rel="noopener noreferrer">'
                f'<span class="post-date">{_html_escape(post.get("date", "") or "")}</span>'
                f'<span class="post-title">{_html_escape(post["title"])}</span>'
                f'<span class="post-desc">{_html_escape(desc)}</span></a>'
            )
        substack_html = (
            '<div class="home-section">'
            '<div class="home-module-head"><h3>From Our Substack</h3></div>'
            '<div class="post-cards">' + "".join(cards) + "</div>"
            '<p class="module-more"><a href="https://speechmap.substack.com/" target="_blank" rel="noopener noreferrer">All posts →</a></p>'
            "</div>"
        )
    else:
        substack_html = (
            '<div class="home-section">'
            '<div class="home-module-head"><h3>From Our Substack</h3></div>'
            '<a class="post-card" href="https://speechmap.substack.com/" target="_blank" rel="noopener noreferrer">'
            '<span class="post-title">Read our analysis and updates on Substack</span>'
            '<span class="post-desc">Lab leaderboard updates, new-model results, and commentary on the shifting boundaries of AI speech.</span></a>'
            "</div>"
        )

    body = (
        # Full-width hero with map background
        "<div class=\"hero-full\">"
        + _hero_trend_svg(model_summary) +
        "  <div class=\"hero-overlay\">"
        "    <h1>Mapping the Invisible<br>Boundaries of AI Speech</h1>"
        "    <p class=\"hero-subtitle\">Tracking what AI models refuse to say, and how it's changing over time.</p>"
        "    <p class=\"hero-cta\"><a href=\"/labs/\">Lab Leaderboard</a><a class=\"cta-secondary\" href=\"/timeline/\">Model Timeline</a></p>"
        "  </div>"
        "</div>"
        "<div class=\"about-content\">"
        # Two-column grid: narrative + leaderboard stacked left, the tall
        # What We Found box (findings + trend) spanning on the right.
        "  <div class=\"two-col-grid\">"
        "    <div class=\"text-column\">"
        "      <h3>What is SpeechMap.AI?</h3>"
        "      <p><b>SpeechMap.AI</b> is a public research project that maps the boundaries of AI speech. We put the same set of sensitive and controversial requests — political argument, satire, religion, history, rights advocacy — to ChatGPT, Claude, Gemini, Grok, DeepSeek, and hundreds of other AI models, and record what gets answered, what gets hedged, and what gets refused.</p>"
        "      <p>Most benchmarks measure what language models <i>can</i> do. We measure what they <i>won't</i>: we publish refusal rates for every model release from every major provider. Every model has boundaries, but they're undocumented, inconsistent between providers and topics, and quietly redrawn with each new release.</p>"
        "      <p>Our point is not that every request deserves an answer. Some are offensive. Some are absurd. But AI assistants are becoming part of how people write, search, learn, and argue — and whether you call it safety, content moderation, or censorship, the limits of machine speech increasingly shape the limits of public speech. SpeechMap makes those limits visible: measured, compared, and tracked over time.</p>"
        + standings_html +
        "    </div>"
        "    <div class=\"content-box\">"
        "      <h3>What We Found</h3>"
        "      <div class=\"wf-figures\">"
        f"        <div class=\"wf-fig\"><span class=\"wf-num\">{models}</span><span class=\"wf-cap\">models tested</span></div>"
        f"        <div class=\"wf-fig\"><span class=\"wf-num\">{judgments / 1000:.0f}k</span><span class=\"wf-cap\">responses analyzed</span></div>"
        "      </div>"
        "      <p class=\"patterns-label\">Models apply different standards to similar requests:</p>"
        + findings_html +
        "    </div>"
        "  </div>"
        + substack_html
        + recent_html +
        # Support section
        "  <div class=\"help-section\">"
        "    <h3>Support the Project</h3>"
        "    <p>Evaluating one model can cost <b>tens to hundreds of dollars</b> in API fees. Our goal is exhaustive coverage, and older models are already disappearing. You can help:</p>"
        "    <div class=\"support-links\">"
        "      <a href=\"https://ko-fi.com/speechmap\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"support-link\">"
        "        <svg viewBox=\"0 0 24 24\" fill=\"currentColor\"><path d=\"M23.881 8.948c-.773-4.085-4.859-4.593-4.859-4.593H.723c-.604 0-.679.798-.679.798s-.082 7.324-.022 11.822c.164 2.424 2.586 2.672 2.586 2.672s8.267-.023 11.966-.049c2.438-.426 2.683-2.566 2.658-3.734 4.352.24 7.422-2.831 6.649-6.916zm-11.062 3.511c-1.246 1.453-4.011 3.976-4.011 3.976s-.121.119-.31.023c-.076-.057-.108-.09-.108-.09-.443-.441-3.368-3.049-4.034-3.954-.709-.965-1.041-2.7-.091-3.71.951-1.01 3.005-1.086 4.363.407 0 0 1.565-1.782 3.468-.963 1.904.82 1.832 3.011.723 4.311zm6.173.478c-.928.116-1.682.028-1.682.028V7.284h1.77s1.971.551 1.971 2.638c0 1.913-.985 2.667-2.059 3.015z\"/></svg>"
        "        Support us on Ko-fi"
        "      </a>"
        "      <a href=\"https://speechmap.substack.com/\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"support-link\">"
        "        <svg viewBox=\"0 0 24 24\" fill=\"currentColor\"><path d=\"M22.539 8.242H1.46V5.406h21.08v2.836zM1.46 10.812V24L12 18.11 22.54 24V10.812H1.46zM22.54 0H1.46v2.836h21.08V0z\"/></svg>"
        "        Subscribe on Substack"
        "      </a>"
        "    </div>"
        "  </div>"
        "</div>"
    )
    return head + body + _page_foot(depth=0)


def _model_table_html(model_summary, filter_placeholder="Filter models… (supports /regex/)", sort="released"):
    """Sortable/filterable model table (shared by the models index, per-lab
    and per-domain pages). `sort` picks the prerendered order: "released"
    (date desc) or "complete" (% complete desc)."""
    rows = []
    if sort == "complete":
        ordered = sorted(
            model_summary,
            key=lambda m: float(m.get("pct_complete_overall") or 0.0),
            reverse=True,
        )
    else:
        ordered = sorted(
            model_summary,
            key=lambda m: (m.get("release_date") or ""),
            reverse=True,
        )
    expected = max((int(m.get("num_responses") or 0) for m in ordered), default=0)
    for m in ordered:
        model = m.get("model", "")
        safe = generate_safe_id(model)
        link = f"/models/{safe}/"
        pcts = {
            "complete": m.get("pct_complete_overall", 0),
            "evasive": m.get("pct_evasive", 0),
            "denial": m.get("pct_denial", 0),
            "error": m.get("pct_error", 0),
        }
        data_attrs = " ".join(
            f'data-s-{k}="{_pct_value(v)}"' for k, v in pcts.items()
        )
        # Most models have every response; flag the rare shortfalls as a
        # footnote instead of dedicating a column to a non-event.
        n_resp = int(m.get("num_responses") or 0)
        note = ""
        if expected and n_resp < expected:
            note = (
                f'<span class="resp-note" data-tip="Incomplete data: only {n_resp:,} of '
                f'{expected:,} responses were collected for this model here">†</span>'
            )
        rows.append(
            f'<tr data-f="{_html_escape(model.lower())}"'
            f' data-s-model="{_html_escape(model.lower())}"'
            f' data-s-released="{_html_escape(m.get("release_date","") or "")}"'
            f" {data_attrs}>"
            f'<td class="td-name"><a href="{link}">{_html_escape(model)}</a>{note}</td>'
            f'<td class="td-meta">{_html_escape(m.get("release_date","") or "")}</td>'
            f'<td class="td-num td-complete">{_pct(m.get("pct_complete_overall",0))}</td>'
            f'<td class="td-bar">{_verdict_bar_html(pcts)}</td>'
            f"</tr>"
        )
    columns = [
        {"label": "Model", "sort_key": "model", "sort_type": "text", "first_dir": "asc"},
        {"label": "Released", "sort_key": "released", "sort_type": "text", "first_dir": "desc"},
        {"label": "% Complete", "sort_key": "complete", "sort_type": "num", "first_dir": "desc", "th_class": "num"},
        {"label": "Breakdown", "chips": True},
    ]
    return _data_table_html(
        columns,
        "\n".join(rows),
        filter_placeholder=filter_placeholder,
        initial_sort=("complete", "desc") if sort == "complete" else ("released", "desc"),
    )


def render_models_index(model_summary):
    title = "Model Results"
    canon = f"{SITE_BASE_URL}/models/"
    depth = 1
    table_html = _model_table_html(model_summary)
    prompt_count = max((int(m.get("num_responses") or 0) for m in model_summary), default=0)
    table = f"""
<div class=\"leaderboard-hero\">
  <h1>Model Results</h1>
  <p class=\"hero-subtitle\">Refusal rates for every model release from every major provider</p>
</div>
<div class=\"leaderboard-content\">
  <div class=\"leaderboard-intro\">
    <div class=\"intro-main\">
      <p>Every model below faced the same {prompt_count:,} sensitive and controversial prompts. <b>% Complete</b> is the share it answered in full \u2014 the bar shows the full outcome mix. Click a model for its per-theme breakdown, or use the filter to compare labs and model families.</p>
      <p class=\"column-legend\"><b>Complete:</b> fully answered · <b>Evasive:</b> hedged or redirected · <b>Denial:</b> refused · <b>Error:</b> blocked by the provider</p>
    </div>
  </div>
""" + table_html + "\n</div>\n"
    return _page_head(title, canon, depth=depth, active_tab='models') + table + _page_foot(depth=depth)


def render_model_detail(model_id, meta, theme_stats_for_model, lab_metadata=None, domain_ranks=None):
    title = f"Model: {model_id}"
    canon = f"{SITE_BASE_URL}/models/{generate_safe_id(model_id)}/"
    depth = 2

    # Extract key metadata
    creator = (meta or {}).get("creator", "Unknown")
    creator_display = lab_display_name(creator, lab_metadata)
    model_name = (meta or {}).get("model_name", model_id)
    release_date = (meta or {}).get("release_date", "")
    model_family = (meta or {}).get("model_family", "")
    is_reasoning = (meta or {}).get("reasoning_model", False)

    # Hero header
    hero_html = f"""
<div class="leaderboard-hero">
  <h1>{_html_escape(model_name)}</h1>
  <p class="hero-subtitle">{_html_escape(creator_display)}</p>
</div>
<div class="leaderboard-content">
<p class="back-link"><a href="../">← Back to Models</a></p>
"""

    # Calculate overall stats
    total_responses = 0
    total_complete = 0
    total_evasive = 0
    total_denial = 0
    total_error = 0
    for key, s in (theme_stats_for_model or {}).items():
        c = int(s.get("c", 0))
        total_responses += c
        total_complete += int(s.get("k", 0))
        total_evasive += int(s.get("e", 0))
        total_denial += int(s.get("d", 0))
        total_error += int(s.get("r", 0))

    pct_complete = (total_complete / total_responses * 100) if total_responses > 0 else 0
    pct_evasive = (total_evasive / total_responses * 100) if total_responses > 0 else 0
    pct_denial = (total_denial / total_responses * 100) if total_responses > 0 else 0
    pct_error = (total_error / total_responses * 100) if total_responses > 0 else 0
    num_themes = len(theme_stats_for_model or {})

    # Model info card - include all key fields
    info_items = []
    info_items.append(f'<div class="info-item"><span class="info-label">Creator</span><span class="info-value">{_html_escape(creator_display)}</span></div>')
    info_items.append(f'<div class="info-item"><span class="info-label">Model Name</span><span class="info-value">{_html_escape(model_name)}</span></div>')
    if model_family:
        info_items.append(f'<div class="info-item"><span class="info-label">Family</span><span class="info-value">{_html_escape(model_family)}</span></div>')
    if release_date:
        info_items.append(f'<div class="info-item"><span class="info-label">Released</span><span class="info-value">{_html_escape(release_date)}</span></div>')
    reasoning_text = "Yes" if is_reasoning else "No"
    info_items.append(f'<div class="info-item"><span class="info-label">Reasoning Model</span><span class="info-value">{reasoning_text}</span></div>')

    info_section = f'<div class="model-info-section"><h3>Model Information</h3><div class="model-info-bar">{"".join(info_items)}</div></div>'

    # Overall stats
    stats_html = f"""
<div class="theme-stats">
  <h3>Overall Results</h3>
  <div class="stats-grid">
    <div class="stat-box"><span class="stat-value">{num_themes}</span><span class="stat-label">Themes Tested</span></div>
    <div class="stat-box"><span class="stat-value">{total_responses}</span><span class="stat-label">Total Responses</span></div>
    <div class="stat-box stat-complete"><span class="stat-value">{pct_complete:.1f}%</span><span class="stat-label">Complete</span></div>
    <div class="stat-box stat-evasive"><span class="stat-value">{pct_evasive:.1f}%</span><span class="stat-label">Evasive</span></div>
    <div class="stat-box stat-denial"><span class="stat-value">{pct_denial:.1f}%</span><span class="stat-label">Denial</span></div>
    <div class="stat-box stat-error"><span class="stat-value">{pct_error:.1f}%</span><span class="stat-label">Error</span></div>
  </div>
  <div class="overall-bar">{_verdict_bar_html({"complete": pct_complete, "evasive": pct_evasive, "denial": pct_denial, "error": pct_error})}</div>
</div>
"""

    # Build theme rows
    rows = []
    items = []
    for key, s in (theme_stats_for_model or {}).items():
        c = int(s.get("c", 0))
        pct_c = (s.get("k", 0) / c * 100) if c > 0 else 0
        items.append((key, s.get("domain") or "N/A", c, pct_c, s))
    items.sort(key=lambda x: x[0])  # Sort by theme name ascending
    expected_per_theme = max((it[2] for it in items), default=0)
    for key, dom, c, pct_c, s in items:
        theme_link = f"/themes/{generate_safe_id(key)}/m/{generate_safe_id(model_id)}/"
        pcts = {
            "complete": pct_c,
            "evasive": (s.get('e', 0) / c * 100) if c > 0 else 0,
            "denial": (s.get('d', 0) / c * 100) if c > 0 else 0,
            "error": (s.get('r', 0) / c * 100) if c > 0 else 0,
        }
        data_attrs = " ".join(
            f'data-s-{k}="{_pct_value(v)}"' for k, v in pcts.items()
        )
        note = ""
        if expected_per_theme and c < expected_per_theme:
            note = (
                f'<span class="resp-note" data-tip="Incomplete data: only {c} of '
                f'{expected_per_theme} responses were collected for this theme">†</span>'
            )
        rows.append(
            f'<tr data-f="{_html_escape((key + " " + dom).lower())}"'
            f' data-s-theme="{_html_escape(key.lower())}"'
            f' data-s-domain="{_html_escape(dom.lower())}"'
            f" {data_attrs}>"
            f'<td class="td-name"><a href="{theme_link}">{_html_escape(key)}</a>{note}</td>'
            f'<td class="td-meta">{_html_escape(dom)}</td>'
            f'<td class="td-num td-complete">{_pct(pct_c)}</td>'
            f'<td class="td-bar">{_verdict_bar_html(pcts)}</td>'
            f"</tr>"
        )
    columns = [
        {"label": "Theme", "sort_key": "theme", "sort_type": "text", "first_dir": "asc"},
        {"label": "Domain", "sort_key": "domain", "sort_type": "text", "first_dir": "asc"},
        {"label": "% Complete", "sort_key": "complete", "sort_type": "num", "first_dir": "desc", "th_class": "num"},
        {"label": "Breakdown", "chips": True},
    ]
    # Performance by domain: the model's outcome mix per domain, most
    # refused first, with the gap vs the median model as a signed number.
    dom_agg = defaultdict(lambda: {"c": 0, "k": 0, "e": 0, "d": 0, "r": 0})
    for key, st in (theme_stats_for_model or {}).items():
        dom = st.get("domain") or "Other"
        for f in ("c", "k", "e", "d", "r"):
            dom_agg[dom][f] += int(st.get(f, 0) or 0)
    dev_rows = []
    for dom, agg in dom_agg.items():
        if not agg["c"]:
            continue
        pcts = {
            "complete": agg["k"] / agg["c"] * 100,
            "evasive": agg["e"] / agg["c"] * 100,
            "denial": agg["d"] / agg["c"] * 100,
            "error": agg["r"] / agg["c"] * 100,
        }
        rank_info = (domain_ranks or {}).get(dom, {}).get(model_id)
        dev_rows.append((pcts["complete"], dom, pcts, rank_info))
    dev_rows.sort()
    devs_html = ""
    if dev_rows:
        rows_html = []
        for mine, dom, pcts, rank_info in dev_rows:
            slug = generate_safe_id(dom)
            if rank_info is None:
                rank_html = ""
            else:
                rank, total, ties = rank_info
                third = "pos" if rank <= total / 3 else ("neg" if rank > 2 * total / 3 else "")
                tie_note = (
                    f" \u2014 {ties} models share this score (positions {rank}\u2013{rank + ties - 1})"
                    if ties > 1 else ""
                )
                rank_html = (
                    f'<span class="dm-med dev-val {third}" '
                    f'data-tip="Ranked #{rank} of {total} models by % answered completely on this domain{tie_note}">'
                    f"#{rank}</span>"
                )
            rows_html.append(
                f'<div class="domain-row dev-row" data-domain="{_html_escape(dom)}" '
                f'title="Filter the theme table to {_html_escape(dom)}">'
                f'<span class="dm-name">{_html_escape(dom)}</span>'
                f'<span class="dm-pct">{mine:.1f}%</span>'
                f'<span class="dm-bar">{_verdict_bar_html(pcts)}</span>'
                f"{rank_html}"
                f'<a class="dev-open" href="/domains/{slug}/" title="Open the {_html_escape(dom)} domain page">↗</a>'
                "</div>"
            )
        n_total = next((v[1] for d in (domain_ranks or {}).values() for v in d.values()), 0)
        devs_html = (
            '<div class="theme-stats"><h3>Performance by Domain</h3>'
            f'<p class="module-blurb">This model\u2019s outcome mix on each question domain, '
            f'most refused first, with its rank among the {n_total} tested models. '
            'Click a row to filter the theme table below; ↗ opens the domain page.</p>'
            '<div class="domain-devs" id="domain-devs">'
            '<div class="domain-row dev-head" aria-hidden="true">'
            '<span class="dm-name"></span><span class="dm-pct">% comp</span>'
            '<span class="dm-bar"></span><span class="dm-med">rank</span>'
            '<span class="dev-open"></span></div>'
            + "".join(rows_html) + "</div></div>"
        )

    table = (
        devs_html
        + "\n<h3>Compliance by Question Theme</h3>\n"
        + _data_table_html(
            columns,
            "\n".join(rows),
            filter_placeholder="Filter themes…",
            initial_sort=("theme", "asc"),
        )
        + "\n</div>\n"
    )
    seo_title = f"{model_id} \u2014 Refusal Rates & Censorship Scores | SpeechMap.AI"
    seo_desc = (
        f"How {model_name} handles controversial speech: answered {pct_complete:.1f}% of "
        f"{total_responses} sensitive prompts completely, refused {pct_denial:.1f}%. "
        f"Per-theme refusal breakdown on SpeechMap.AI."
    )
    return _page_head(seo_title, canon, depth=depth, active_tab='models', description=seo_desc) + hero_html + info_section + stats_html + table + _page_foot(depth=depth)


def render_themes_index(theme_summary_all, model_theme_summary=None):
    title = "Question Themes"
    canon = f"{SITE_BASE_URL}/themes/"
    depth = 1
    rows = []
    ordered = sorted(
        theme_summary_all,
        key=lambda t: float(t.get("pct_complete_overall") or 0.0),
    )
    for t in ordered:
        key = t.get("grouping_key", "")
        dom = t.get("domain", "") or ""
        link = f"/themes/{generate_safe_id(key)}/"
        pcts = {
            "complete": t.get("pct_complete_overall", 0),
            "evasive": t.get("pct_evasive", 0),
            "denial": t.get("pct_denial", 0),
            "error": t.get("pct_error", 0),
        }
        data_attrs = " ".join(
            f'data-s-{k}="{_pct_value(v)}"' for k, v in pcts.items()
        )
        rows.append(
            f'<tr data-f="{_html_escape((key + " " + dom).lower())}"'
            f' data-s-theme="{_html_escape(key.lower())}"'
            f' data-s-domain="{_html_escape(dom.lower())}"'
            f' data-s-models="{t.get("num_models",0)}"'
            f' data-s-resp="{t.get("num_responses",0)}" {data_attrs}>'
            f'<td class="td-name"><a href="{link}">{_html_escape(key)}</a></td>'
            f'<td class="td-meta">{_html_escape(dom)}</td>'
            f'<td class="td-num td-complete">{_pct(t.get("pct_complete_overall",0))}</td>'
            f'<td class="td-bar">{_verdict_bar_html(pcts)}</td>'
            f"</tr>"
        )
    n_themes = len(theme_summary_all or [])
    n_domains = len({t.get("domain") for t in (theme_summary_all or []) if t.get("domain")})
    header_html = f"""
<div class=\"leaderboard-hero\">
  <h1>Question Themes</h1>
  <p class=\"hero-subtitle\">What models will answer, topic by topic</p>
</div>
<div class=\"leaderboard-content\">
  <div class=\"leaderboard-intro\">
    <div class=\"intro-main\">
      <p>SpeechMap\u2019s question set is organized into {n_themes} themes across {n_domains} domains \u2014 each theme is one underlying request, asked several ways. The table starts with the most-refused themes; click any theme for its exact prompts and every model\u2019s responses.</p>
      <p class=\"column-legend\"><b>Complete:</b> fully answered · <b>Evasive:</b> hedged or redirected · <b>Denial:</b> refused · <b>Error:</b> blocked by the provider</p>
    </div>
  </div>
"""
    # Domain overview: one row per domain; dots are MODELS (each model's
    # % complete on that domain) so dots mean the same thing site-wide.
    theme_counts = defaultdict(int)
    for t in theme_summary_all or []:
        theme_counts[t.get("domain") or "Other"] += 1
    dom_model = _domain_model_rollups(model_theme_summary)
    dom_rows = []
    for dom, models in dom_model.items():
        vals = sorted(a["k"] / a["c"] * 100 for a in models.values() if a["c"])
        if not vals:
            continue
        n = len(vals)
        med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
        dom_rows.append((med, dom, vals))
    dom_rows.sort()
    overview_rows = []
    def _beeswarm_offsets(count):
        # 0, +3, -3, +6, -6, ... capped so dots stay inside the row
        offs = [0]
        step = 3
        while len(offs) < count:
            offs.append(min(step, 9))
            offs.append(-min(step, 9))
            step += 3
        return offs[:count]

    for med, dom, vals in dom_rows:
        # Small-theme domains quantize scores (16 prompts -> 6.25% steps);
        # fanning same-score stacks vertically turns banding into tidy
        # histogram-like columns.
        stacks = defaultdict(list)
        for v in vals:
            stacks[round(v, 1)].append(v)
        dot_parts = []
        for sval in sorted(stacks):
            group = stacks[sval]
            for v, off in zip(group, _beeswarm_offsets(len(group))):
                dot_parts.append(
                    f'<i class="sp-dot" style="left:{max(0.0, min(100.0, v)):.1f}%;'
                    f'top:calc(50% + {off}px)"></i>'
                )
        dots = "".join(dot_parts)
        overview_rows.append(
            f'<a class="domain-row" href="/domains/{generate_safe_id(dom)}/">'
            f'<span class="dm-name">{_html_escape(dom)} <i class="dm-count">{theme_counts.get(dom, 0)} themes</i></span>'
            f'<span class="dm-strip"><span class="stripplot">{dots}'
            f'<i class="sp-index" style="left:{med:.1f}%"></i></span></span>'
            f'<span class="dm-med">{med:.1f}</span>'
            "</a>"
        )
    overview_html = (
        '<div class="domain-overview" id="domain-overview">'
        '<div class="home-module-head"><h3>By Domain</h3>'
        '<span class="module-note">dot = one model \u00b7 tick = median model % complete</span></div>'
        '<p class="module-blurb">Click a domain for its trend, themes, and per-model rankings. All themes are searchable in the table below.</p>'
        + "".join(overview_rows)
        + "</div>"
    )

    columns = [
        {"label": "Theme", "sort_key": "theme", "sort_type": "text", "first_dir": "asc"},
        {"label": "Domain", "sort_key": "domain", "sort_type": "text", "first_dir": "asc"},
        {"label": "% Complete", "sort_key": "complete", "sort_type": "num", "first_dir": "desc", "th_class": "num"},
        {"label": "Breakdown", "chips": True},
    ]
    table = overview_html + _data_table_html(
        columns,
        "\n".join(rows),
        filter_placeholder="Filter themes… (supports /regex/)",
        initial_sort=("complete", "asc"),
    ) + "\n</div>\n"
    return _page_head(title, canon, depth=depth, active_tab='themes') + header_html + table + _page_foot(depth=depth)


def render_lab_standings_page(lab_standings, lab_metadata=None, model_summary=None, model_metadata=None):
    title = "Lab Leaderboard"
    canon = f"{SITE_BASE_URL}/labs/"
    depth = 0
    data = lab_standings or {}
    standings = data.get("standings") or []
    window_months = data.get("window_months", LAB_STANDINGS_WINDOW_MONTHS)
    window_mode = data.get("window_mode") or "rolling_global"
    as_of_str = data.get("as_of") or date.today().isoformat()
    try:
        as_of_date = date.fromisoformat(as_of_str)
    except Exception:
        as_of_date = date.today()
    cards = []
    # Strip plot data: each lab's model scores within its standings window,
    # plus an all-time rollup per lab (drives the off-leaderboard table).
    lab_models = defaultdict(list)
    lab_rollup = {}
    for m in model_summary or []:
        meta_m = (model_metadata or {}).get(m.get("model"), {})
        cr = meta_m.get("creator")
        rd = m.get("release_date") or ""
        if cr and rd:
            try:
                lab_models[cr].append((rd, float(m.get("pct_complete_overall") or 0.0)))
            except (TypeError, ValueError):
                pass
        if cr:
            roll = lab_rollup.setdefault(
                cr,
                {"n": 0.0, "count": 0, "latest": "",
                 "agg": {"complete": 0.0, "evasive": 0.0, "denial": 0.0, "error": 0.0}},
            )
            n = float(m.get("num_responses") or 0)
            roll["n"] += n
            roll["count"] += 1
            roll["agg"]["complete"] += float(m.get("pct_complete_overall") or 0.0) * n
            roll["agg"]["evasive"] += float(m.get("pct_evasive") or 0.0) * n
            roll["agg"]["denial"] += float(m.get("pct_denial") or 0.0) * n
            roll["agg"]["error"] += float(m.get("pct_error") or 0.0) * n
            if rd > roll["latest"]:
                roll["latest"] = rd

    standings_keys = {row.get("lab") for row in standings}
    off_rows = []
    for cr, roll in lab_rollup.items():
        if cr in standings_keys or cr.strip().lower() == "unknown":
            continue
        tot = roll["n"]
        pcts = {k: (v / tot if tot else 0.0) for k, v in roll["agg"].items()}
        off_rows.append((pcts["complete"], cr, pcts, roll["count"], roll["latest"]))
    off_rows.sort(key=lambda r: (-r[0], r[1]))
    other_labs_html = ""
    if off_rows:
        body = "".join(
            "<tr>"
            f'<td class="lab-name"><a href="/labs/{generate_safe_id(cr)}/">{_html_escape(lab_display_name(cr, lab_metadata))}</a></td>'
            f'<td class="trend">{_pct_value(pc)}</td>'
            f'<td class="mix-cell">{_verdict_bar_html(pcts)}</td>'
            f'<td class="count">{ct}</td>'
            f'<td class="count">{_html_escape(latest)}</td>'
            "</tr>"
            for pc, cr, pcts, ct, latest in off_rows
        )
        other_labs_html = f"""
  <div class=\"off-board\">
    <h3>Off the Leaderboard</h3>
    <p class=\"module-blurb\">Labs with no tested release in the last {window_months} months. The windowed index doesn't apply, so these show all-time results across every model we tested — % answered completely and the full outcome mix.</p>
    <div class=\"lab-leaderboard-table-wrap\">
      <table class=\"leaderboard-table off-board-table\">
        <thead><tr><th>Lab</th><th>% Complete</th><th class=\"mix-cell\">Response Mix</th><th>Models</th><th>Latest Release</th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
  </div>"""

    for i, row in enumerate(standings, start=1):
        lab_key = row.get("lab", "")
        lab = lab_display_name(lab_key, lab_metadata)
        try:
            idx_v = max(0.0, min(100.0, float(row.get("consistency") or 0.0)))
            peak_v = max(0.0, min(100.0, float(row.get("peak_score") or 0.0)))
        except (TypeError, ValueError):
            idx_v, peak_v = 0.0, 0.0
        models_ct = int(row.get("models_in_window", 0))
        ws = row.get("window_start") or ""
        we = row.get("window_end") or ""
        scores = sorted(
            max(0.0, min(100.0, v))
            for rd, v in lab_models.get(lab_key, [])
            if (not ws or rd >= ws) and (not we or rd <= we)
        )
        strip = ""
        if scores:
            lo, hi = scores[0], scores[-1]
            dots = "".join(f'<i class="sp-dot" style="left:{v:.1f}%"></i>' for v in scores)
            strip = (
                '<span class="stripplot">'
                f'<i class="sp-band" style="left:{lo:.1f}%;width:{max(0.0, hi - lo):.1f}%"></i>'
                f"{dots}"
                f'<i class="sp-index" style="left:{idx_v:.1f}%"></i>'
                "</span>"
            )
        cards.append(
            f"<tr>"
            f"<td class=\"rank\">#{i}</td>"
            f'<td class="lab-name"><a href="/labs/{generate_safe_id(lab_key)}/">{_html_escape(lab)}</a></td>'
            f"<td class=\"trend\">{_pct_value(idx_v)}</td>"
            f"<td class=\"peak\">{_pct_value(peak_v)}</td>"
            f'<td class="spark-cell">{strip}</td>'
            f"<td class=\"count\">{models_ct}</td>"
            f"</tr>"
        )
    if not cards:
        cards.append("<tr><td colspan=\"6\" class=\"empty\">No labs with releases in this window.</td></tr>")
    table = f"""
<div class=\"leaderboard-hero\">
  <h1>Lab Leaderboard</h1>
  <p class=\"hero-subtitle\">Which AI labs build models that best support user speech?</p>
</div>
<div class=\"leaderboard-content\">
  <div class=\"leaderboard-intro\">
    <div class=\"intro-main\">
      <h3>What We Measure</h3>
      <p><b>SpeechMap.AI</b> tests how AI models respond to sensitive and controversial prompts. A model's score is the share of requests it answers completely, rather than refusing, hedging, or filtering \u2014 higher means the model engages more directly.</p>
      <p>Labs are ranked by their <b>Free Speech Index</b>: a time-weighted average of model scores in each lab's latest release cycle ({window_months} months, anchored to that lab's most recent release). <b>Peak</b> is the lab's best single model in that window. Only labs with a release in the last {window_months} months are shown. Click any lab for its full history, or see the <a href=\"/models/\">Models</a> page for individual results.</p>
    </div>
    <div class=\"intro-meta\">
      <p class=\"meta-note\">Last updated: {as_of_date.isoformat()}</p>
    </div>
  </div>
  <div class=\"sp-legend\"><span class=\"sp-legend-item\"><i class=\"sp-index sp-demo\"></i> Index</span><span class=\"sp-legend-item\"><i class=\"sp-dot sp-demo\"></i> one model release</span></div>\n  <div class=\"lab-leaderboard-table-wrap\">
    <table class=\"leaderboard-table\">
      <thead><tr><th>Rank</th><th>Lab</th><th>Index</th><th>Peak</th><th class=\"spark-cell\">Recent Model Scores (0\u2013100)</th><th>Models</th></tr></thead>
      <tbody>
{''.join(cards)}
      </tbody>
    </table>
  </div>
{other_labs_html}
</div>
"""
    return _page_head(title, canon, depth=depth, active_tab='labs') + table + _page_foot(depth=depth)


def render_lab_page(lab_key, models, standings_entry, rank, lab_metadata=None, domain_rows=None):
    """Per-lab hub page: standings summary, aggregate verdict mix, and the
    lab's models as a sortable table."""
    name = lab_display_name(lab_key, lab_metadata)
    safe = generate_safe_id(lab_key)
    canon = f"{SITE_BASE_URL}/labs/{safe}/"

    # Aggregate verdict mix, weighted by responses per model.
    tot = 0.0
    agg = {"complete": 0.0, "evasive": 0.0, "denial": 0.0, "error": 0.0}
    latest = ""
    for m in models:
        n = float(m.get("num_responses") or 0)
        tot += n
        agg["complete"] += float(m.get("pct_complete_overall") or 0.0) * n
        agg["evasive"] += float(m.get("pct_evasive") or 0.0) * n
        agg["denial"] += float(m.get("pct_denial") or 0.0) * n
        agg["error"] += float(m.get("pct_error") or 0.0) * n
        rd = m.get("release_date") or ""
        if rd > latest:
            latest = rd
    pcts = {k: (v / tot if tot else 0.0) for k, v in agg.items()}

    info_items = []
    if rank and standings_entry:
        info_items.append(f'<div class="info-item"><span class="info-label">Leaderboard Rank</span><span class="info-value">#{rank}</span></div>')
        info_items.append(f'<div class="info-item"><span class="info-label">Index</span><span class="info-value">{_pct_value(standings_entry.get("consistency", 0))}</span></div>')
        info_items.append(f'<div class="info-item"><span class="info-label">Peak</span><span class="info-value">{_pct_value(standings_entry.get("peak_score", 0))}</span></div>')
    info_items.append(f'<div class="info-item"><span class="info-label">Models Tested</span><span class="info-value">{len(models)}</span></div>')
    if latest:
        info_items.append(f'<div class="info-item"><span class="info-label">Latest Release</span><span class="info-value">{_html_escape(latest)}</span></div>')
    standings_note = "" if (rank and standings_entry) else '<p class="module-blurb">Not currently on the leaderboard (no release in the standings window).</p>'

    n_models = len(models)
    plural = "s" if n_models != 1 else ""
    rank_sentence = (
        f" {name} currently ranks #{rank} on the SpeechMap Free Speech Index."
        if (rank and standings_entry) else ""
    )
    lede = (
        f"How do {name}\u2019s AI models handle controversial speech? SpeechMap has put "
        f"{n_models} {name} model{plural} through the same set of sensitive prompts \u2014 "
        f"political argument, religion, satire, history \u2014 measuring what gets answered "
        f"and what gets refused. Across {int(tot):,} responses, {name} models answered "
        f"{pcts['complete']:.1f}% of requests completely and refused {pcts['denial']:.1f}%."
        + rank_sentence
    )
    title = f"{name} \u2014 AI Model Refusal Rates | SpeechMap.AI"
    description = (
        f"How censored are {name}\u2019s AI models? Refusal rates and free-speech scores for "
        f"{n_models} {name} model{plural}: {pcts['complete']:.1f}% of controversial requests "
        f"answered completely, {pcts['denial']:.1f}% refused. Full results on SpeechMap.AI."
    )
    head = _page_head(title, canon, depth=1, active_tab='labs', description=description)

    traj_svg = _overall_trend_svg(models, width=1000, height=240, scatter=True) if n_models >= 2 else ""
    timeline_link = (
        f'<a href="/timeline/?highlight={quote_plus(lab_key)}">explore on the interactive timeline →</a>'
    )
    if traj_svg:
        trajectory_html = (
            "<h3>Score Trajectory</h3>"
            f'<div class="trend-figure lab-traj">{traj_svg}</div>'
            f'<p class="findings-note">Model scores by release date, with the time-weighted trend · {timeline_link}</p>'
        )
    else:
        trajectory_html = f'<p class="module-more">{timeline_link}</p>'

    # Index by Domain: the leaderboard's windowed EMA computed per domain,
    # ranked against other eligible labs. Alphabetical by domain.
    domain_index_html = ""
    if domain_rows:
        rows_html = []
        for dom, idx, drank, dn, dties, mix in sorted(domain_rows, key=lambda r: r[0]):
            slug = generate_safe_id(dom)
            third = "pos" if drank <= dn / 3 else ("neg" if drank > 2 * dn / 3 else "")
            tie_note = (
                f" \u2014 {dties} labs share this score (positions {drank}\u2013{drank + dties - 1})"
                if dties > 1 else ""
            )
            rows_html.append(
                f'<div class="domain-row dev-row-static">'
                f'<span class="dm-name"><a href="/domains/{slug}/">{_html_escape(dom)}</a></span>'
                f'<span class="dm-pct">{idx:.1f}</span>'
                f'<span class="dm-bar">{_verdict_bar_html(mix)}</span>'
                f'<span class="dm-med dev-val {third}" '
                f'data-tip="Ranked #{drank} of {dn} labs by domain Free Speech Index (same time-weighted window as the leaderboard){tie_note}">'
                f"#{drank}</span>"
                "</div>"
            )
        domain_index_html = (
            '<div class="theme-stats"><h3>Index by Domain</h3>'
            f'<p class="module-blurb">The Free Speech Index computed per question domain \u2014 same '
            f'release window and time-weighting as the leaderboard \u2014 with {_html_escape(name)}\u2019s '
            'rank among eligible labs. Bars show the outcome mix of the '
            'window\u2019s models.</p>'
            '<div class="domain-devs">'
            '<div class="domain-row dev-head" aria-hidden="true">'
            '<span class="dm-name"></span><span class="dm-pct">index</span>'
            '<span class="dm-bar"></span><span class="dm-med">rank</span></div>'
            + "".join(rows_html) + "</div></div>"
        )

    body = (
        '<div class="leaderboard-hero">'
        f"  <h1>{_html_escape(name)}</h1>"
        '  <p class="hero-subtitle">Lab results on SpeechMap</p>'
        "</div>"
        '<div class="leaderboard-content">'
        '<p class="back-link"><a href="/labs/">← Back to Leaderboard</a></p>'
        f'<p class="lab-lede">{_html_escape(lede)}</p>'
        f'<div class="model-info-section"><h3>Lab Summary</h3><div class="model-info-bar">{"".join(info_items)}</div></div>'
        + standings_note +
        '<div class="theme-stats"><h3>Overall Response Mix</h3>'
        '<div class="stats-grid">'
        f'<div class="stat-box stat-complete"><span class="stat-value">{pcts["complete"]:.1f}%</span><span class="stat-label">Complete</span></div>'
        f'<div class="stat-box stat-evasive"><span class="stat-value">{pcts["evasive"]:.1f}%</span><span class="stat-label">Evasive</span></div>'
        f'<div class="stat-box stat-denial"><span class="stat-value">{pcts["denial"]:.1f}%</span><span class="stat-label">Denial</span></div>'
        f'<div class="stat-box stat-error"><span class="stat-value">{pcts["error"]:.1f}%</span><span class="stat-label">Error</span></div>'
        "</div>"
        f'<div class="overall-bar">{_verdict_bar_html(pcts)}</div>'
        "</div>"
        + trajectory_html
        + domain_index_html +
        "<h3>Models</h3>"
        + _model_table_html(models)
        + "</div>"
    )
    return head + body + _page_foot(depth=1)


def compute_lab_domain_indexes(model_summary, model_metadata, model_theme_summary,
                                 months=LAB_STANDINGS_WINDOW_MONTHS,
                                 half_life_months=LAB_STANDINGS_HALFLIFE_MONTHS):
    """Per-lab, per-domain Free Speech Index: the leaderboard's windowed,
    gap-aware monthly EMA, computed on each domain's themes only. Returns
    (indexes, mixes, ranks): indexes[lab][dom] = score; mixes[lab][dom] =
    verdict pcts over the lab's window models; ranks[dom][lab] = (rank, n)."""
    # Per-model per-domain tallies.
    model_dom = defaultdict(dict)
    for mid, themes in (model_theme_summary or {}).items():
        for tkey, st in themes.items():
            dom = st.get("domain") or "Other"
            agg = model_dom[mid].setdefault(dom, {"c": 0, "k": 0, "e": 0, "d": 0, "r": 0})
            for f in ("c", "k", "e", "d", "r"):
                agg[f] += int(st.get(f, 0) or 0)

    today = date.today()
    recent_cutoff = _months_ago(today, months)
    labs = defaultdict(list)
    for m in model_summary or []:
        mid = m.get("model")
        meta = (model_metadata or {}).get(mid, {})
        creator = meta.get("creator")
        if not creator or creator.strip().lower() == "unknown":
            continue
        rd = _parse_date_safe(meta.get("release_date"))
        if rd:
            labs[creator].append((rd, mid))

    indexes = defaultdict(dict)
    mixes = defaultdict(dict)
    for lab, items in labs.items():
        anchor_date = max(rd for rd, _ in items)
        if anchor_date < recent_cutoff:
            continue
        cutoff = _months_ago(anchor_date, months)
        window = [(rd, mid) for rd, mid in items if cutoff <= rd <= anchor_date]
        by_dom_pairs = defaultdict(list)
        by_dom_mix = defaultdict(lambda: {"c": 0, "k": 0, "e": 0, "d": 0, "r": 0})
        for rd, mid in window:
            for dom, agg in model_dom.get(mid, {}).items():
                if not agg["c"]:
                    continue
                by_dom_pairs[dom].append((f"{rd.year:04d}-{rd.month:02d}", agg["k"] / agg["c"] * 100))
                for f in ("c", "k", "e", "d", "r"):
                    by_dom_mix[dom][f] += agg[f]
        for dom, pairs in by_dom_pairs.items():
            series = _monthly_ema_series(pairs, half_life_months=half_life_months)
            if series:
                indexes[lab][dom] = series[-1][1]
                mx = by_dom_mix[dom]
                mixes[lab][dom] = {
                    "complete": mx["k"] / mx["c"] * 100,
                    "evasive": mx["e"] / mx["c"] * 100,
                    "denial": mx["d"] / mx["c"] * 100,
                    "error": mx["r"] / mx["c"] * 100,
                }

    ranks = {}
    all_doms = {d for v in indexes.values() for d in v}
    for dom in all_doms:
        scored = sorted(((round(v[dom], 4), lab) for lab, v in indexes.items() if dom in v), reverse=True)
        ranks[dom] = _competition_rank(scored)
    return indexes, mixes, ranks


def generate_lab_pages(model_summary, model_metadata, lab_standings, lab_metadata=None, model_theme_summary=None):
    """Write /labs/<slug>/ hub pages for every creator with tested models."""
    by_lab = defaultdict(list)
    for m in model_summary or []:
        meta = (model_metadata or {}).get(m.get("model"), {})
        cr = meta.get("creator")
        if cr and cr.strip().lower() != "unknown":
            by_lab[cr].append(m)
    ranks = {}
    entries = {}
    for i, row in enumerate((lab_standings or {}).get("standings") or [], start=1):
        ranks[row.get("lab")] = i
        entries[row.get("lab")] = row

    dom_indexes, dom_mixes, dom_ranks = ({}, {}, {})
    if model_theme_summary:
        dom_indexes, dom_mixes, dom_ranks = compute_lab_domain_indexes(
            model_summary, model_metadata, model_theme_summary
        )
    for lab_key, models in by_lab.items():
        safe = generate_safe_id(lab_key)
        out_dir = os.path.join(STATIC_LABS_DIR, safe)
        os.makedirs(out_dir, exist_ok=True)
        _write_file(
            os.path.join(out_dir, "index.html"),
            render_lab_page(
                lab_key, models, entries.get(lab_key), ranks.get(lab_key),
                lab_metadata=lab_metadata,
                domain_rows=[
                    (dom, idx, *dom_ranks[dom][lab_key], dom_mixes[lab_key][dom])
                    for dom, idx in dom_indexes.get(lab_key, {}).items()
                    if dom in dom_ranks and lab_key in dom_ranks[dom]
                ],
            ),
        )
    return sorted(by_lab.keys())


STATIC_DOMAINS_DIR = "domains"


def render_domain_page(domain, theme_rows, model_rows, n_domains, global_median=None):
    """Domain hub: how every model performs on this territory (strip +
    rankings), then the domain's themes. The middle layer between /themes/
    and theme pages."""
    slug = generate_safe_id(domain)
    canon = f"{SITE_BASE_URL}/domains/{slug}/"
    n_themes = len(theme_rows)
    n_models = len(model_rows)

    mvals = sorted(float(m.get("pct_complete_overall") or 0.0) for m in model_rows)
    med = (
        mvals[n_models // 2] if n_models % 2 else (mvals[n_models // 2 - 1] + mvals[n_models // 2]) / 2
    ) if n_models else 0.0

    title = f"{domain} \u2014 AI Refusal Rates by Topic | SpeechMap.AI"
    desc = (
        f"How AI models handle {domain} questions: {n_models} models tested on "
        f"{n_themes} themes; the median model answers {med:.0f}% completely. "
        f"Per-model rankings and per-theme prompts on SpeechMap.AI."
    )
    head = _page_head(title, canon, depth=1, active_tab='themes', description=desc)

    gap_sentence = ""
    if global_median is not None:
        gap = med - global_median
        if abs(gap) >= 1:
            direction = "less" if gap < 0 else "more"
            gap_sentence = (
                f" \u2014 {abs(gap):.0f} points {direction} than the {global_median:.0f}% they "
                f"answer across all domains"
            )
    lede = (
        f"{domain} is one of SpeechMap\u2019s {n_domains} question domains: {n_themes} themes, "
        f"each asking a different underlying request from this territory. The median model "
        f"answers {med:.0f}% of this domain\u2019s prompts completely{gap_sentence}. "
        f"Below: the trend over time, how every model ranks here, and each theme with its "
        f"prompts and responses."
    )

    # Score trajectory: model releases scored on this domain, with the
    # time-weighted trend — the same chart lab pages use, scoped here.
    traj_svg = _overall_trend_svg(model_rows, width=1000, height=240, scatter=True)
    if traj_svg:
        strip_html = (
            "<h3>Score Trajectory</h3>"
            f'<div class="trend-figure lab-traj">{traj_svg}</div>'
            '<p class="findings-note">Model scores on this domain by release date, with the time-weighted trend</p>'
        )
    else:
        strip_html = ""

    model_table = _model_table_html(model_rows, sort="complete")

    # Theme table (lives in a tab, so height no longer buries anything).
    trows = []
    for t in sorted(theme_rows, key=lambda t: float(t.get("pct_complete_overall") or 0.0)):
        key = t.get("grouping_key", "")
        tp = {
            "complete": t.get("pct_complete_overall", 0),
            "evasive": t.get("pct_evasive", 0),
            "denial": t.get("pct_denial", 0),
            "error": t.get("pct_error", 0),
        }
        data_attrs = " ".join(f'data-s-{k}="{_pct_value(v)}"' for k, v in tp.items())
        trows.append(
            f'<tr data-f="{_html_escape((key or "").lower())}" data-s-theme="{_html_escape((key or "").lower())}" {data_attrs}>'
            f'<td class="td-name"><a href="/themes/{generate_safe_id(key)}/">{_html_escape(key)}</a></td>'
            f'<td class="td-num td-complete">{_pct(t.get("pct_complete_overall", 0))}</td>'
            f'<td class="td-bar">{_verdict_bar_html(tp)}</td>'
            "</tr>"
        )
    theme_columns = [
        {"label": "Theme", "sort_key": "theme", "sort_type": "text", "first_dir": "asc"},
        {"label": "% Complete", "sort_key": "complete", "sort_type": "num", "first_dir": "desc", "th_class": "num"},
        {"label": "Breakdown", "chips": True},
    ]
    theme_table = _data_table_html(
        theme_columns,
        "\n".join(trows),
        filter_placeholder="Filter themes…",
        initial_sort=("complete", "asc"),
    )

    tabs_html = (
        '<div class="tab-bar" id="domain-tabs">'
        f'<button type="button" class="tab-btn active" data-tab="themes">Themes ({n_themes})</button>'
        f'<button type="button" class="tab-btn" data-tab="models">Model Rankings ({n_models})</button>'
        "</div>"
        f'<section class="tab-panel active" id="tab-themes">'
        '<p class="module-blurb">Most refused first \u00b7 click a theme for its exact prompts and every model\u2019s answers.</p>'
        f"{theme_table}</section>"
        f'<section class="tab-panel" id="tab-models">'
        '<p class="module-blurb">Each model\u2019s results across every theme in this domain, most willing first.</p>'
        f"{model_table}</section>"
    )

    body = (
        '<div class="leaderboard-hero">'
        f"  <h1>{_html_escape(domain)}</h1>"
        '  <p class="hero-subtitle">SpeechMap question domain</p>'
        "</div>"
        '<div class="leaderboard-content">'
        '<p class="back-link"><a href="/themes/">← All domains and themes</a></p>'
        f'<div class="page-intro"><p class="lab-lede">{lede}</p>{WHY_WE_TEST_HTML}</div>'
        + strip_html
        + tabs_html
        + "</div>"
    )
    return head + body + _page_foot(depth=1)


def _domain_model_rollups(model_theme_summary):
    """dom -> model -> summed {c,k,e,d,r} across the domain's themes."""
    dom_model = defaultdict(lambda: defaultdict(lambda: {"c": 0, "k": 0, "e": 0, "d": 0, "r": 0}))
    for mid, themes in (model_theme_summary or {}).items():
        for tkey, st in themes.items():
            dom = st.get("domain") or "Other"
            agg = dom_model[dom][mid]
            for f in ("c", "k", "e", "d", "r"):
                agg[f] += int(st.get(f, 0) or 0)
    return dom_model


def _competition_rank(scored):
    """[(score, key), ...] sorted desc -> {key: (rank, total, ties)}.
    Ties share the best rank (competition/"1224" ranking): on quantized
    domains hundreds of models tie, and sort-order ranks would be fiction."""
    total = len(scored)
    out = {}
    i = 0
    while i < total:
        j = i
        while j < total and scored[j][0] == scored[i][0]:
            j += 1
        for _, key in scored[i:j]:
            out[key] = (i + 1, total, j - i)
        i = j
    return out


def _domain_model_ranks(dom_model):
    """dom -> {model: (rank, total, ties)} by %-complete, rank 1 = most willing."""
    ranks = {}
    for dom, models in dom_model.items():
        scored = sorted(
            ((round(agg["k"] / agg["c"] * 100, 4), mid) for mid, agg in models.items() if agg["c"]),
            reverse=True,
        )
        ranks[dom] = _competition_rank(scored)
    return ranks


def generate_domain_pages(qts_all, model_theme_summary, model_metadata):
    """Write /domains/<slug>/ pages. Returns domain slugs for the sitemap."""
    by_domain = defaultdict(list)
    for t in qts_all or []:
        by_domain[t.get("domain") or "Other"].append(t)

    dom_model = _domain_model_rollups(model_theme_summary)

    # Site-wide median model score (each model's overall % complete),
    # used as the reference tick on every domain strip.
    overall = defaultdict(lambda: {"c": 0, "k": 0})
    for models in dom_model.values():
        for mid, agg in models.items():
            overall[mid]["c"] += agg["c"]
            overall[mid]["k"] += agg["k"]
    ovals = sorted(a["k"] / a["c"] * 100 for a in overall.values() if a["c"])
    global_median = (
        ovals[len(ovals) // 2] if len(ovals) % 2 else (ovals[len(ovals) // 2 - 1] + ovals[len(ovals) // 2]) / 2
    ) if ovals else 0.0

    n_domains = len(by_domain)
    slugs = []
    for domain, theme_rows in by_domain.items():
        model_rows = []
        for mid, agg in dom_model.get(domain, {}).items():
            c = agg["c"]
            if not c:
                continue
            meta = (model_metadata or {}).get(mid, {})
            model_rows.append({
                "model": mid,
                "release_date": meta.get("release_date", "") or "",
                "num_responses": c,
                "pct_complete_overall": agg["k"] / c * 100,
                "pct_evasive": agg["e"] / c * 100,
                "pct_denial": agg["d"] / c * 100,
                "pct_error": agg["r"] / c * 100,
            })
        slug = generate_safe_id(domain)
        out_dir = os.path.join(STATIC_DOMAINS_DIR, slug)
        os.makedirs(out_dir, exist_ok=True)
        _write_file(
            os.path.join(out_dir, "index.html"),
            render_domain_page(domain, theme_rows, model_rows, n_domains, global_median),
        )
        slugs.append(slug)
    return sorted(slugs)


def render_timeline_page(lab_metadata=None):
    """Timeline static shell. Legend chips are prerendered from lab colors so
    the client needs no metadata fetch to know the color tier; Chart.js
    hydration loads point data from /data/."""
    head = _page_head("Model Timeline", f"{SITE_BASE_URL}/timeline/", depth=0, active_tab='timeline')
    colored = sorted(
        (
            (lab, meta.get("full_name") or lab, meta.get("color"))
            for lab, meta in (lab_metadata or {}).items()
            if isinstance(meta, dict) and meta.get("color")
        ),
        key=lambda x: x[1].lower(),
    )
    chips = [
        f'<button type="button" class="tl-chip" data-lab="{_html_escape(lab)}" data-color="{_html_escape(color)}">'
        f'<i class="dot" style="background:{_html_escape(color)}"></i>{_html_escape(name)}</button>'
        for lab, name, color in colored
    ]
    chips.append(
        '<span class="tl-chip tl-swatch"><i class="dot" style="background:#b0b7c3"></i>Other labs</span>'
    )
    chips.append(
        '<button type="button" class="tl-chip tl-clear" id="timeline-clear-highlights" hidden>&#10005; Clear</button>'
    )
    legend_html = (
        '<div class="timeline-legend" id="timeline-legend">'
        '<span class="tl-legend-label">Highlight</span>'
        '<div class="tl-chips-wrap">' + "".join(chips) + "</div></div>"
    )
    body = (
        "<div class=\"leaderboard-hero\">"
        "  <h1>Model Timeline</h1>"
        "  <p class=\"hero-subtitle\">Track how model compliance changes over time</p>"
        "</div>"
        "<div class=\"leaderboard-content\">"
        "<div class=\"timeline-view-container\">"
        "<div class=\"leaderboard-intro\"><div class=\"intro-main\">"
        "<p>This scatter plot shows each model's release date against its compliance rate. "
        "Hover a lab in the legend to spotlight it; click to pin one or more labs and compare "
        "their trend lines. Use the filters to explore by metric or creator. "
        "Click any point to view that model's details.</p>"
        "</div></div>"
        "<div class=\"timeline-filters filter-controls\">"
        "  <div class=\"filter-item\"><label for=\"timeline-metric-filter\">Y-Axis Metric:</label>"
        "    <select id=\"timeline-metric-filter\"></select></div>"
        "  <div class=\"filter-item\"><label for=\"timeline-creator-filter\">Creator:</label>"
        "    <select id=\"timeline-creator-filter\"></select></div>"
        "  <div class=\"filter-item\"><label for=\"timeline-highlight-creator-filter\">Highlight Lab:</label>"
        "    <select id=\"timeline-highlight-creator-filter\"></select></div>"
        "</div>"
        + legend_html +
        "<div class=\"chart-container\"><canvas id=\"timeline-chart-canvas\"></canvas></div>"
        "</div></div>"
    )
    foot = (
        "\n<script src=\"https://cdn.jsdelivr.net/npm/chart.js@^4\"></script>\n"
        "<script src=\"https://cdn.jsdelivr.net/npm/date-fns@^2\"></script>\n"
        "<script src=\"https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@^3\"></script>\n"
        + _page_foot(depth=0)
    )
    return head + body + foot


def _resource_card(href, title, desc, external=True):
    ext_attrs = ' target="_blank" rel="noopener noreferrer"' if external else ""
    ext_cls = " external" if external else ""
    return (
        f'<a class="resource-card{ext_cls}" href="{_html_escape(href)}"{ext_attrs}>'
        f'<span class="resource-title">{_html_escape(title)}</span>'
        f'<span class="resource-desc">{_html_escape(desc)}</span></a>'
    )


def render_resources_page():
    head = _page_head("Resources & Data", f"{SITE_BASE_URL}/resources/", depth=0, active_tab='resources')
    body = (
        "<div class=\"leaderboard-hero\">"
        "  <h1>Resources &amp; Data</h1>"
        "  <p class=\"hero-subtitle\">Our data, code, and writing — and how to support the project</p>"
        "</div>"
        "<div class=\"leaderboard-content\"><div class=\"resources-content\">"
        "<h3>Data</h3>"
        + _resource_card(
            "https://huggingface.co/collections/xlr8harder/speechmap",
            "SpeechMap collection on Hugging Face",
            "Formal data releases: packaged datasets of model responses and judge assessments, published periodically.",
        )
        + _resource_card(
            "https://github.com/xlr8harder/llm-compliance",
            "llm-compliance on GitHub",
            "The complete, up-to-date working dataset — every response and judgment behind the current site — plus the evaluation harness that produces it (question sets, scraping, judging, and analysis tools).",
        )
        + "<h3>Code</h3>"
        + _resource_card(
            "https://github.com/xlr8harder/speechmap",
            "speechmap on GitHub",
            "This website: the static site generator and the aggregate data behind the pages you're reading.",
        )
        + "<h3>Writing &amp; Updates</h3>"
        + _resource_card(
            "https://speechmap.substack.com/",
            "SpeechMap on Substack",
            "Analysis, lab leaderboard updates, and new-model announcements.",
        )
        + "<h3>Support &amp; Thanks</h3>"
        + _resource_card(
            "https://ko-fi.com/speechmap",
            "Support us on Ko-fi",
            "Evaluating a single model can cost tens to hundreds of dollars in API fees — donations directly fund coverage.",
        )
        + _resource_card(
            "/acknowledgments/",
            "Acknowledgments",
            "The supporters who made this project possible.",
            external=False,
        )
        + "</div></div>"
    )
    return head + body + _page_foot(depth=0)


def render_acknowledgments_page():
    return _page_head("Acknowledgments", f"{SITE_BASE_URL}/acknowledgments/", depth=0, active_tab='ack') + (
        "<div class=\"leaderboard-hero\">"
        "  <h1>Acknowledgments</h1>"
        "  <p class=\"hero-subtitle\">Thank you to our supporters</p>"
        "</div>"
        "<div class=\"leaderboard-content\">"
        "<div class=\"acknowledgments-content\">"
        "<h3>Our Supporters</h3>"
        "<p>We're deeply indebted to <a href=\"https://x.com/jon_durbin\">Jon Durbin</a>, who provided the initial seed funds needed to launch the project.</p>"
        "<p>We're grateful to <a href=\"https://openrouter.ai\">OpenRouter</a> for their generous support shortly after our launch. Their contribution helped us complete coverage of all key models from all major model providers for our initial post-launch milestone, and their infrastructure made this project far more feasible than it would have been otherwise.</p>"
        "<div class=\"ack-support-section\">"
        "<h3>Support the Project</h3>"
        "<p>Running comprehensive evaluations across hundreds of AI models is expensive. Each model evaluation can cost <b>tens to hundreds of dollars</b> in API fees, and we're committed to maintaining exhaustive coverage as new models are released.</p>"
        "<p>Your support helps us:</p>"
        "<ul>"
        "<li>Evaluate new models as they're released</li>"
        "<li>Maintain coverage of existing models over time</li>"
        "<li>Expand our prompt coverage to new domains</li>"
        "<li>Keep the project independent and ad-free</li>"
        "</ul>"
        "<p>If you find this research valuable, please consider supporting us:</p>"
        "<div class=\"support-links\">"
        "<a href=\"https://ko-fi.com/speechmap\" target=\"_blank\" rel=\"noopener noreferrer\" class=\"support-link\">"
        "<svg viewBox=\"0 0 24 24\" fill=\"currentColor\"><path d=\"M23.881 8.948c-.773-4.085-4.859-4.593-4.859-4.593H.723c-.604 0-.679.798-.679.798s-.082 7.324-.022 11.822c.164 2.424 2.586 2.672 2.586 2.672s8.267-.023 11.966-.049c2.438-.426 2.683-2.566 2.658-3.734 4.352.24 7.422-2.831 6.649-6.916zm-11.062 3.511c-1.246 1.453-4.011 3.976-4.011 3.976s-.121.119-.31.023c-.076-.057-.108-.09-.108-.09-.443-.441-3.368-3.049-4.034-3.954-.709-.965-1.041-2.7-.091-3.71.951-1.01 3.005-1.086 4.363.407 0 0 1.565-1.782 3.468-.963 1.904.82 1.832 3.011.723 4.311zm6.173.478c-.928.116-1.682.028-1.682.028V7.284h1.77s1.971.551 1.971 2.638c0 1.913-.985 2.667-2.059 3.015z\"/></svg>"
        "Support us on Ko-fi"
        "</a>"
        "</div>"
        "</div>"
        "</div></div>"
    ) + _page_foot(depth=0)


def _summarize_theme_across_models(theme_key, model_theme_summary):
    # Build per-model summary rows for one theme
    rows = []
    for model, themes in model_theme_summary.items():
        s = themes.get(theme_key)
        if not s:
            continue
        c = int(s.get("c", 0))
        if c <= 0:
            continue
        pct_c = (s.get("k", 0) / c * 100) if c > 0 else 0
        rows.append((model, s.get("domain") or "N/A", c, pct_c, s))
    rows.sort(key=lambda x: (x[3], x[0]))
    return rows


def _theme_sample_from_records(records, limit=THEME_SAMPLE_LIMIT):
    # Diverse sample: one per model round-robin until limit
    from collections import defaultdict
    by_model = defaultdict(list)
    for r in records:
        by_model[r.get("model")].append(r)
    # simple round robin
    sample = []
    models = sorted(by_model.keys())
    idx = 0
    while len(sample) < limit and models:
        m = models[idx % len(models)]
        lst = by_model[m]
        if lst:
            sample.append(lst.pop(0))
        models = [mm for mm in models if by_model[mm]]
        idx += 1
    return sample


THEME_SHARD_COUNT = 8
THEME_SHARDS_DIR = os.path.join("data", "theme-shards")
PAIR_TEMPLATE_FILE = os.path.join("data", "pair-template.html")


def _fnv1a(s):
    """FNV-1a 32-bit — trivially portable to the Pages Function in JS."""
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _theme_shard_of(model_safe_id):
    return _fnv1a(model_safe_id) % THEME_SHARD_COUNT


def _render_response_cards(theme_safe, model, records):
    """HTML fragment for one model's responses on one theme. Stored in the
    theme shards; injected client-side on the theme page and server-side by
    the pair-page Pages Function."""
    safe = generate_safe_id(model)
    arr = sorted(records, key=lambda r: int(r.get("variation") or 0))
    out = [
        '<div class="model-expanded-actions">'
        f'<a href="/themes/{theme_safe}/m/{safe}/">Permalink →</a>'
        f'<span class="mea-sep">·</span>'
        f'<a href="/models/{safe}/">All results for {_html_escape(model)} →</a>'
        "</div>"
    ]
    for r in arr:
        comp = r.get("compliance") or ""
        q = r.get("question_text") or ""
        response_text = r.get("response_text") or ""
        ans = md_to_html(response_text)
        jtxt = _html_escape(r.get("judge_analysis") or "")
        var = r.get("variation") or ""
        moderation_reason = r.get("original_moderation_reason")
        moderation_note_html = ""
        if moderation_reason:
            reason = _html_escape(str(moderation_reason))
            if response_text:
                note = (
                    "Provider moderation stopped this response "
                    f"({reason}). Any model response shown below may be partial."
                )
            else:
                note = (
                    "Provider moderation stopped this response "
                    f"({reason}). No model response text was returned."
                )
            moderation_note_html = f'<div class="moderation-note">{note}</div>'
        api_provider = (r.get("api_provider") or "").strip().lower()
        has_api_fields = "api_provider" in r
        or_slug = r.get("api_model") if has_api_fields else r.get("model")
        show_openrouter = bool(or_slug) and (not has_api_fields or "openrouter" in api_provider)
        openrouter_html = ""
        if show_openrouter:
            openrouter = f"https://openrouter.ai/chat?models={quote_plus(or_slug or '')}&message={quote_plus(q)}"
            openrouter_html = (
                '<div class="detail-section action-section">'
                f'<a class="openrouter-link" href="{_html_escape(openrouter)}" target="_blank" rel="noopener noreferrer">'
                '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                '<path d="M18 13v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>'
                '<polyline points="15 3 21 3 21 9"/>'
                '<line x1="10" y1="14" x2="21" y2="3"/>'
                "</svg>"
                "<span>Try on OpenRouter →</span>"
                "</a></div>"
            )
        out.append(
            '<div class="response-card-nested">'
            f'<div class="response-header nested-header"><strong>Variation {_html_escape(var)}</strong> · '
            f'<span class="compliance-label compliance-{_html_escape(comp)}">{_html_escape(comp)}</span></div>'
            '<div class="response-content-area nested-content">'
            f"{moderation_note_html}"
            f'<div class="detail-section"><strong>Prompt:</strong><pre class="text-display prompt-inline">{_html_escape(q)}</pre></div>'
            f'<div class="detail-section"><strong>Model Response:</strong><div class="text-display markdown-content">{ans}</div></div>'
            f'<div class="detail-section"><strong>Judge Analysis:</strong><pre class="text-display">{jtxt}</pre></div>'
            f"{openrouter_html}"
            "</div></div>"
        )
    return "".join(out)


def _verdict_bucket(records):
    comps = [r.get("compliance") for r in records]
    if comps and all(c == "COMPLETE" for c in comps):
        return 0
    if comps and all(c == "DENIAL" for c in comps):
        return 2
    if comps and all(c == "ERROR" for c in comps):
        return 3
    return 1


WHY_WE_TEST_HTML = (
    '<div class="context-note">'
    "<b><a href=\"/\">SpeechMap.AI</a></b> is a public research project that maps the "
    "boundaries of AI speech. Every major model is asked the same sensitive and "
    "controversial questions \u2014 some deliberately provocative \u2014 and we publish "
    "what each answers, hedges, or refuses, so models can be compared and changes "
    "tracked over time."
    "</div>"
)


VERDICT_SYMBOLS = {
    "COMPLETE": "\u2713",  # check
    "EVASIVE": "~",
    "DENIAL": "\u2715",   # cross
    "ERROR": "!",
}


VERDICT_BUCKETS = (
    ("Answered everything", "All prompt variations answered completely."),
    ("Mixed responses", "Some variations answered, others hedged or refused."),
    ("Refused everything", "All prompt variations denied."),
    ("Errors only", "No scoreable responses (API blocks or failures)."),
)


def render_theme_detail(theme_key, domain, per_model_rows, sample_records):
    """Static theme page: prompts, stats, and models grouped by outcome in
    collapsible sections. Response bodies live in shard files (written here
    too) and are lazy-loaded on expand / served by the pair-page Function."""
    theme_safe = generate_safe_id(theme_key)
    title = f"Theme: {theme_key}"
    canon = f"{SITE_BASE_URL}/themes/{theme_safe}/"
    depth = 2

    groups = {}
    for r in sample_records or []:
        m = r.get("model") or "Unknown"
        groups.setdefault(m, []).append(r)

    # --- Shards + per-theme meta (assets for lazy-load and the Function) ---
    os.makedirs(THEME_SHARDS_DIR, exist_ok=True)
    shards = [dict() for _ in range(THEME_SHARD_COUNT)]
    for m, arr in groups.items():
        safe = generate_safe_id(m)
        shards[_theme_shard_of(safe)][safe] = {
            "m": m,
            "html": _render_response_cards(theme_safe, m, arr),
        }
    for k, shard in enumerate(shards):
        with open(os.path.join(THEME_SHARDS_DIR, f"{theme_safe}.{k}.json"), "w", encoding="utf-8") as f:
            json.dump(shard, f, ensure_ascii=False)
    with open(os.path.join(THEME_SHARDS_DIR, f"{theme_safe}.meta.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"theme": theme_key, "domain": domain or "N/A", "shards": THEME_SHARD_COUNT},
            f,
            ensure_ascii=False,
        )

    # --- Prompts + stats ---
    prompts_seen = {}
    for r in sample_records or []:
        var = r.get("variation") or "1"
        if r.get("question_text") and var not in prompts_seen:
            prompts_seen[var] = r["question_text"]
    prompts_html = '<div class="theme-prompts"><h3>Prompts Used</h3>'
    if prompts_seen:
        for var in sorted(prompts_seen.keys(), key=lambda x: int(x) if x.isdigit() else 0):
            prompts_html += (
                f'<div class="prompt-item"><span class="prompt-label">Variation {_html_escape(var)}:</span>'
                f'<pre class="prompt-text">{_html_escape(prompts_seen[var])}</pre></div>'
            )
    else:
        prompts_html += "<p>No prompts available.</p>"
    prompts_html += "</div>"

    total_responses = len(sample_records or [])
    total_models = len(groups)
    counts = {c: sum(1 for r in (sample_records or []) if r.get("compliance") == c) for c in ("COMPLETE", "EVASIVE", "DENIAL", "ERROR")}
    pct_complete = (counts["COMPLETE"] / total_responses * 100) if total_responses else 0
    pct_evasive = (counts["EVASIVE"] / total_responses * 100) if total_responses else 0
    pct_denial = (counts["DENIAL"] / total_responses * 100) if total_responses else 0
    pct_error = (counts["ERROR"] / total_responses * 100) if total_responses else 0

    n_vars = len(prompts_seen) or 4
    lede = (
        f"This is one of SpeechMap\u2019s {_html_escape(domain or '')} themes: {n_vars} variations "
        f"of one underlying request, put to {total_models} AI models. Below are the exact "
        f"prompts, the overall outcome, and every model grouped by how it responded \u2014 "
        f"click any model for its full responses and judge analysis."
    )
    hero_html = f"""
<div class="leaderboard-hero">
  <h1>{_html_escape(theme_key)}</h1>
  <p class="hero-subtitle">{_html_escape(domain or 'N/A')}</p>
</div>
<div class="leaderboard-content">
<p class="back-link"><a href="../">← Back to Themes</a></p>
<div class="page-intro"><p class="lab-lede">{lede}</p>{WHY_WE_TEST_HTML}</div>
"""

    stats_html = f"""
<div class="theme-stats">
  <h3>Overall Results</h3>
  <div class="stats-grid">
    <div class="stat-box"><span class="stat-value">{total_models}</span><span class="stat-label">Models Tested</span></div>
    <div class="stat-box"><span class="stat-value">{total_responses}</span><span class="stat-label">Total Responses</span></div>
    <div class="stat-box stat-complete"><span class="stat-value">{pct_complete:.1f}%</span><span class="stat-label">Complete</span></div>
    <div class="stat-box stat-evasive"><span class="stat-value">{pct_evasive:.1f}%</span><span class="stat-label">Evasive</span></div>
    <div class="stat-box stat-denial"><span class="stat-value">{pct_denial:.1f}%</span><span class="stat-label">Denial</span></div>
    <div class="stat-box stat-error"><span class="stat-value">{pct_error:.1f}%</span><span class="stat-label">Error</span></div>
  </div>
  <div class="overall-bar">{_verdict_bar_html({"complete": pct_complete, "evasive": pct_evasive, "denial": pct_denial, "error": pct_error})}</div>
</div>
"""

    # --- Models in outcome columns; chips link to per-model pair pages ---
    bucketed = [[] for _ in VERDICT_BUCKETS]
    for m in sorted(groups):
        bucketed[_verdict_bucket(groups[m])].append(m)

    columns = []
    for bi, (btitle, bdesc) in enumerate(VERDICT_BUCKETS):
        models = bucketed[bi]
        if not models:
            continue
        chips = []
        for m in models:
            safe = generate_safe_id(m)
            arr = sorted(groups[m], key=lambda r: int(r.get("variation") or 0))
            badges = "".join(
                f'<span class="compliance-badge badge-{(r.get("compliance") or "unknown").lower()}" '
                f'title="Variation {_html_escape(r.get("variation") or "")}: {_html_escape((r.get("compliance") or "UNKNOWN").title())}">'
                f'{VERDICT_SYMBOLS.get(r.get("compliance"), "?")}</span>'
                for r in arr
            )
            chips.append(
                f'<a class="mchip" id="model-{safe}" href="/themes/{theme_safe}/m/{safe}/">'
                f'<span class="mchip-name">{_html_escape(m)}</span>'
                f'<span class="model-badges">{badges}</span></a>'
            )
        columns.append(
            f'<section class="vg-col vg-col-{bi}"><h3 class="vg-title">{btitle} <span class="vg-count">{len(models)}</span></h3>'
            f'<p class="vg-desc">{bdesc}</p><div class="vg-chips">' + "".join(chips) + "</div></section>"
        )

    controls_html = """
<div class="model-responses-header">
  <h3>Model Responses</h3>
  <p class="module-blurb">Click any model for its full responses and judge analysis on this theme.</p>
</div>
"""

    body_html = (
        hero_html
        + prompts_html
        + stats_html
        + controls_html
        + f'<div class="verdict-columns" data-pair-base="/themes/{theme_safe}/m/">'
        + "".join(columns)
        + "</div></div>"
    )
    head = _page_head(title, canon, depth=depth, active_tab='themes')
    return head + body_html + _page_foot(depth=depth)


def write_pair_template():
    """Chrome template the pair-page Pages Function fills in. Generated with
    the real page head/foot so the Function never duplicates site chrome."""
    head = _page_head("__TITLE__", "__CANONICAL__", depth=2, active_tab='themes', description="__DESC__")
    body = (
        '<div class="leaderboard-hero"><h1>__MODEL__</h1><p class="hero-subtitle">__THEME__ · __DOMAIN__</p></div>'
        '<div class="leaderboard-content">'
        '<p class="back-link"><a href="/themes/__THEME_SAFE__/">← All models on this theme</a></p>'
        + WHY_WE_TEST_HTML +
        '<div class="response-list pair-page">__CARDS__</div>'
        "</div>"
    )
    _write_file(PAIR_TEMPLATE_FILE, head + body + _page_foot(depth=2))
def generate_static_pages(model_meta_dict, summaries, data_by_theme, lab_standings, lab_metadata=None, include_theme_pages=True):
    # Models index
    os.makedirs(STATIC_MODELS_DIR, exist_ok=True)
    _prune_stale_model_dirs(summaries.get("model_summary"))
    models_index_path = os.path.join(STATIC_MODELS_DIR, "index.html")
    _write_file(models_index_path, render_models_index(summaries["model_summary"]))

    # Per-model pages
    domain_ranks = _domain_model_ranks(_domain_model_rollups(summaries["model_theme_summary"]))
    for model in summaries["model_summary"]:
        mid = model.get("model")
        safe = generate_safe_id(mid)
        path = os.path.join(STATIC_MODELS_DIR, safe, "index.html")
        meta = model_meta_dict.get(mid, {})
        theme_stats_for_model = summaries["model_theme_summary"].get(mid, {})
        _write_file(path, render_model_detail(mid, meta, theme_stats_for_model, lab_metadata=lab_metadata, domain_ranks=domain_ranks))

    # Themes index (use all-time summary already computed)
    os.makedirs(STATIC_THEMES_DIR, exist_ok=True)
    themes_index_path = os.path.join(STATIC_THEMES_DIR, "index.html")
    _write_file(themes_index_path, render_themes_index(summaries["question_theme_summary"], summaries["model_theme_summary"]))

    # Domain hub pages
    domain_slugs = generate_domain_pages(summaries["question_theme_summary"], summaries["model_theme_summary"], model_meta_dict)

    # Per-theme pages (use per-model stats + sample records from data_by_theme)
    if include_theme_pages:
        for theme_key, records in data_by_theme.items():
            safe = generate_safe_id(theme_key)
            path = os.path.join(STATIC_THEMES_DIR, safe, "index.html")
            # Determine domain: prefer from per-model stats
            domain_guess = None
            for model, tm in summaries["model_theme_summary"].items():
                s = tm.get(theme_key)
                if s and s.get("domain"):
                    domain_guess = s.get("domain")
                    break
            per_model_rows = _summarize_theme_across_models(theme_key, summaries["model_theme_summary"])
            # Render ALL records for full static detail (include all variations per model)
            _write_file(path, render_theme_detail(theme_key, domain_guess, per_model_rows, records))

    # Lab standings page
    os.makedirs(STATIC_LABS_DIR, exist_ok=True)
    _write_file(os.path.join(STATIC_LABS_DIR, "index.html"), render_lab_standings_page(lab_standings, lab_metadata=lab_metadata, model_summary=summaries["model_summary"], model_metadata=model_meta_dict))
    generate_lab_pages(summaries["model_summary"], model_meta_dict, lab_standings, lab_metadata=lab_metadata)

    # Acknowledgments + Resources static pages
    _write_file(os.path.join("acknowledgments", "index.html"), render_acknowledgments_page())
    os.makedirs("resources", exist_ok=True)
    _write_file(os.path.join("resources", "index.html"), render_resources_page())

    # Timeline static shell (Chart hydration allowed to load data/*)
    _write_file(os.path.join("timeline", "index.html"), render_timeline_page(lab_metadata))
    write_pair_template()


def _write_urlset(filename, urls):
    body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    for loc, lm in urls:
        body.append("  <url>")
        body.append(f"    <loc>{_html_escape(loc)}</loc>")
        body.append(f"    <lastmod>{_html_escape(lm)}</lastmod>")
        body.append("  </url>")
    body.append("</urlset>\n")
    _write_file(filename, "\n".join(body))


SITEMAP_URLS_PER_FILE = 45000


def generate_sitemap_and_robots(model_summary, theme_keys, lab_keys=None, domain_slugs=None):
    """sitemap.xml is an index: one core urlset (site + models + themes +
    labs) plus chunked urlsets for the ~175k model×theme pair pages."""
    today_iso = date.today().isoformat()

    core = []
    core.append((f"{SITE_BASE_URL}/", today_iso))
    core.append((f"{SITE_BASE_URL}/models/", today_iso))
    core.append((f"{SITE_BASE_URL}/themes/", today_iso))
    core.append((f"{SITE_BASE_URL}/labs/", today_iso))
    core.append((f"{SITE_BASE_URL}/timeline/", today_iso))
    core.append((f"{SITE_BASE_URL}/acknowledgments/", today_iso))
    core.append((f"{SITE_BASE_URL}/resources/", today_iso))
    for lk in sorted(lab_keys or []):
        core.append((f"{SITE_BASE_URL}/labs/{generate_safe_id(lk)}/", today_iso))
    for ds in sorted(domain_slugs or []):
        core.append((f"{SITE_BASE_URL}/domains/{ds}/", today_iso))
    for m in model_summary:
        safe = generate_safe_id(m.get("model"))
        core.append((f"{SITE_BASE_URL}/models/{safe}/", m.get("release_date") or today_iso))
    theme_safes = [generate_safe_id(key) for key in theme_keys]
    for safe in theme_safes:
        core.append((f"{SITE_BASE_URL}/themes/{safe}/", today_iso))
    _write_urlset("sitemap-core.xml", core)

    # Pair pages, chunked under the 50k-URL sitemap limit.
    model_entries = [
        (generate_safe_id(m.get("model")), m.get("release_date") or today_iso)
        for m in model_summary
    ]
    pair_urls = [
        (f"{SITE_BASE_URL}/themes/{t}/m/{msafe}/", lastmod)
        for t in sorted(theme_safes)
        for msafe, lastmod in model_entries
    ]
    pair_files = []
    for i in range(0, len(pair_urls), SITEMAP_URLS_PER_FILE):
        fname = f"sitemap-pairs-{i // SITEMAP_URLS_PER_FILE + 1}.xml"
        _write_urlset(fname, pair_urls[i:i + SITEMAP_URLS_PER_FILE])
        pair_files.append(fname)

    index = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
             "<sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    for fname in ["sitemap-core.xml"] + pair_files:
        index.append("  <sitemap>")
        index.append(f"    <loc>{SITE_BASE_URL}/{fname}</loc>")
        index.append(f"    <lastmod>{today_iso}</lastmod>")
        index.append("  </sitemap>")
    index.append("</sitemapindex>\n")
    _write_file("sitemap.xml", "\n".join(index))

    # robots.txt
    robots = f"User-agent: *\nAllow: /\nSitemap: {SITE_BASE_URL}/sitemap.xml\n"
    _write_file("robots.txt", robots)


# ------------------ Static-only generation from Phase 1 artifacts ------------------

def load_core_artifacts():
    """
    Load core metadata and summaries from artifacts in the /.cache layout.
    Expects:
      - /data/metadata-core.json (runtime JSON)
      - /.cache/question-theme-summary/all.json
      - /.cache/model-themes/<model>.json
      - /.cache/theme_details/<theme>.json.gz (optional per-theme details)
    """
    # Core metadata is runtime JSON under /data
    core_path = OUTPUT_CORE_METADATA_FILE
    if not os.path.exists(core_path):
        raise RuntimeError(f"Missing core metadata: {core_path}")

    qts_all_path = os.path.join(OUTPUT_QTHEME_SUMMARY_DIR, "all.json")
    if not os.path.exists(qts_all_path):
        raise RuntimeError(f"Missing question theme summary: {qts_all_path}")

    with open(core_path, "r", encoding="utf-8") as f:
        core = json.load(f)
    with open(qts_all_path, "r", encoding="utf-8") as f:
        qts_all = json.load(f)

    compliance_order = core.get("complianceOrder") or COMPLIANCE_ORDER
    model_meta_dict = core.get("model_metadata", {})
    model_summary = core.get("model_summary", [])
    stats = core.get("stats", {})

    # Build model_theme_summary by loading per-model jsons
    model_theme_summary = {}
    for m in model_summary:
        mid = m.get("model")
        safe = generate_safe_id(mid)
        p = os.path.join(OUTPUT_MODEL_THEMES_DIR, f"{safe}.json")
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    model_theme_summary[mid] = json.load(f)
            except Exception as e:
                print(f"Warning: Failed to load model themes for {mid}: {e}")
        else:
            print(f"Warning: Missing model theme breakdown for {mid}: {p}")
    return model_meta_dict, model_summary, qts_all, model_theme_summary, stats, compliance_order


def load_core_metadata_only():
    """
    Load only the lightweight runtime metadata needed for lab standings.
    """
    core_path = OUTPUT_CORE_METADATA_FILE
    if not os.path.exists(core_path):
        raise RuntimeError(f"Missing core metadata: {core_path}")

    with open(core_path, "r", encoding="utf-8") as f:
        core = json.load(f)

    compliance_order = core.get("complianceOrder") or COMPLIANCE_ORDER
    model_meta_dict = core.get("model_metadata", {})
    model_summary = core.get("model_summary", [])
    stats = core.get("stats", {})
    return model_meta_dict, model_summary, stats, compliance_order


def generate_lab_standings_from_artifacts():
    """
    Regenerate lab standings page from existing runtime artifacts only.
    This avoids loading heavy theme/model artifacts and full analysis data.
    """
    print("Regenerating lab standings from lightweight artifacts...")
    model_meta_dict, model_summary, core_stats, compliance_order = load_core_metadata_only()
    lab_metadata = load_lab_metadata(LAB_METADATA_FILE)
    _, skipped_model_meta = split_model_metadata(load_model_metadata(MODEL_METADATA_FILE))
    if skipped_model_meta:
        skipped_models = set(skipped_model_meta.keys())
        model_meta_dict = {mid: meta for mid, meta in model_meta_dict.items() if mid not in skipped_models}
        model_summary = [m for m in model_summary if m.get("model") not in skipped_models]
        print(f"Applied metadata skip filter in labs-only mode: excluded {len(skipped_models)} model(s).")
    lab_standings = compute_lab_standings(model_summary, model_meta_dict)

    # Keep core metadata in sync with latest lab metadata.
    save_core_metadata(
        OUTPUT_CORE_METADATA_FILE,
        compliance_order,
        core_stats,
        model_meta_dict,
        model_summary,
        lab_metadata=lab_metadata,
    )

    os.makedirs(STATIC_LABS_DIR, exist_ok=True)
    _write_file(os.path.join(STATIC_LABS_DIR, "index.html"), render_lab_standings_page(lab_standings, lab_metadata=lab_metadata, model_summary=model_summary, model_metadata=model_meta_dict))
    # Load per-model theme breakdowns so lab pages keep their Index by
    # Domain section on labs-only regeneration.
    model_theme_summary = {}
    for _m in model_summary:
        _mid = _m.get("model")
        _p = os.path.join(OUTPUT_MODEL_THEMES_DIR, f"{generate_safe_id(_mid)}.json")
        if os.path.exists(_p):
            try:
                with open(_p, "r", encoding="utf-8") as _f:
                    model_theme_summary[_mid] = json.load(_f)
            except Exception:
                pass
    generate_lab_pages(model_summary, model_meta_dict, lab_standings, lab_metadata=lab_metadata, model_theme_summary=model_theme_summary)
    print("Lab standings regeneration complete.")


def regenerate_home_page_from_artifacts():
    """Re-render only index.html from cache artifacts (fast path used by
    --substack-refresh)."""
    model_meta_dict, model_summary, qts_all, model_theme_summary, core_stats, compliance_order = load_core_artifacts()
    _, skipped_model_meta = split_model_metadata(load_model_metadata(MODEL_METADATA_FILE))
    if skipped_model_meta:
        skipped_models = set(skipped_model_meta.keys())
        model_meta_dict = {mid: meta for mid, meta in model_meta_dict.items() if mid not in skipped_models}
        model_summary = [m for m in model_summary if m.get("model") not in skipped_models]
        model_theme_summary = {mid: tm for mid, tm in model_theme_summary.items() if mid not in skipped_models}
        included_models = {m.get("model") for m in model_summary if m.get("model")}
        qts_all = _aggregate_question_theme_summary_for_models(model_theme_summary, included_models)
    lab_metadata = load_lab_metadata(LAB_METADATA_FILE)
    lab_standings = compute_lab_standings(model_summary, model_meta_dict)
    _write_file("index.html", render_home_page(core_stats, qts_all, lab_standings, lab_metadata=lab_metadata, model_summary=model_summary))


def generate_static_pages_from_artifacts(skip_theme_pages=False):
    print("Regenerating static pages from existing artifacts...")
    model_meta_dict, model_summary, qts_all, model_theme_summary, core_stats, compliance_order = load_core_artifacts()
    _, skipped_model_meta = split_model_metadata(load_model_metadata(MODEL_METADATA_FILE))
    if skipped_model_meta:
        skipped_models = set(skipped_model_meta.keys())
        model_meta_dict = {mid: meta for mid, meta in model_meta_dict.items() if mid not in skipped_models}
        model_summary = [m for m in model_summary if m.get("model") not in skipped_models]
        model_theme_summary = {mid: tm for mid, tm in model_theme_summary.items() if mid not in skipped_models}
        included_models = {m.get("model") for m in model_summary if m.get("model")}
        qts_all = _aggregate_question_theme_summary_for_models(model_theme_summary, included_models)
        print(f"Applied metadata skip filter in static-only mode: excluded {len(skipped_models)} model(s).")
    lab_metadata = load_lab_metadata(LAB_METADATA_FILE)
    lab_standings = compute_lab_standings(model_summary, model_meta_dict)
    save_core_metadata(
        OUTPUT_CORE_METADATA_FILE,
        compliance_order,
        core_stats,
        model_meta_dict,
        model_summary,
        lab_metadata=lab_metadata,
    )

    # Root index (About) page — overwrite with correct static content
    _write_file("index.html", render_home_page(core_stats, qts_all, lab_standings, lab_metadata=lab_metadata, model_summary=model_summary))

    # Models index and detail pages
    os.makedirs(STATIC_MODELS_DIR, exist_ok=True)
    _prune_stale_model_dirs(model_summary)
    _write_file(os.path.join(STATIC_MODELS_DIR, "index.html"), render_models_index(model_summary))
    domain_ranks = _domain_model_ranks(_domain_model_rollups(model_theme_summary))
    for m in model_summary:
        mid = m.get("model")
        safe = generate_safe_id(mid)
        path = os.path.join(STATIC_MODELS_DIR, safe, "index.html")
        meta = model_meta_dict.get(mid, {})
        mt = model_theme_summary.get(mid, {})
        _write_file(path, render_model_detail(mid, meta, mt, lab_metadata=lab_metadata, domain_ranks=domain_ranks))

    # Themes index
    os.makedirs(STATIC_THEMES_DIR, exist_ok=True)
    _write_file(os.path.join(STATIC_THEMES_DIR, "index.html"), render_themes_index(qts_all, model_theme_summary))

    # Domain hub pages
    domain_slugs = generate_domain_pages(qts_all, model_theme_summary, model_meta_dict)

    # Lab standings page
    os.makedirs(STATIC_LABS_DIR, exist_ok=True)
    _write_file(os.path.join(STATIC_LABS_DIR, "index.html"), render_lab_standings_page(lab_standings, lab_metadata=lab_metadata, model_summary=model_summary, model_metadata=model_meta_dict))
    generate_lab_pages(model_summary, model_meta_dict, lab_standings, lab_metadata=lab_metadata, model_theme_summary=model_theme_summary)

    # Sitemap + robots (keep in sync for static-only deploys too)
    theme_keys_for_sitemap = [
        t.get("grouping_key")
        for t in (qts_all or [])
        if isinstance(t, dict) and t.get("grouping_key")
    ]
    lab_keys_for_sitemap = sorted({
        (model_meta_dict.get(m.get("model"), {}) or {}).get("creator")
        for m in model_summary
        if (model_meta_dict.get(m.get("model"), {}) or {}).get("creator", "").strip().lower() not in ("", "unknown")
    })
    generate_sitemap_and_robots(model_summary, theme_keys_for_sitemap, lab_keys=lab_keys_for_sitemap, domain_slugs=domain_slugs)

    # Per-theme pages (load gz on demand)
    if not skip_theme_pages:
        for t in qts_all:
            key = t.get("grouping_key")
            if not key:
                continue
            safe = generate_safe_id(key)
            gz_path = os.path.join(OUTPUT_THEME_DETAIL_DIR, f"{safe}.json.gz")
            records = []
            try:
                if os.path.exists(gz_path):
                    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
                        j = json.load(f)
                    records = j.get("records", [])
            except Exception as e:
                print(f"Warning: Failed to read {gz_path}: {e}")
            # Domain guess from model_theme_summary
            domain_guess = None
            for mid, themes in model_theme_summary.items():
                s = themes.get(key)
                if s and s.get("domain"):
                    domain_guess = s.get("domain")
                    break
            out_path = os.path.join(STATIC_THEMES_DIR, safe, "index.html")
            # Render ALL records for full static detail
            _write_file(out_path, render_theme_detail(key, domain_guess, None, records))

    # Acknowledgments + Resources static pages
    _write_file(os.path.join("acknowledgments", "index.html"), render_acknowledgments_page())
    os.makedirs("resources", exist_ok=True)
    _write_file(os.path.join("resources", "index.html"), render_resources_page())

    # Timeline static shell (Chart hydration allowed to load data/*)
    _write_file(os.path.join("timeline", "index.html"), render_timeline_page(lab_metadata))
    write_pair_template()

def main():
    print("Starting preprocessing...")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--labs-only', action='store_true')
    parser.add_argument('--static-only', action='store_true')
    parser.add_argument('--no-themes', action='store_true')
    parser.add_argument('--substack-refresh', action='store_true')
    args, _ = parser.parse_known_args()

    if args.substack_refresh:
        try:
            refresh_substack_cache()
            regenerate_home_page_from_artifacts()
            print("Substack refresh complete.")
        except Exception as e:
            print(f"Substack refresh failed: {e}")
            sys.exit(1)
        return

    if args.labs_only:
        try:
            generate_lab_standings_from_artifacts()
        except Exception as e:
            print(f"Lab standings regeneration failed: {e}")
            sys.exit(1)
        return

    if args.static_only:
        try:
            generate_static_pages_from_artifacts(skip_theme_pages=args.no_themes)
            print("Static regeneration complete.")
        except Exception as e:
            print(f"Static regeneration failed: {e}")
            sys.exit(1)
        return

    model_meta_dict = load_model_metadata(MODEL_METADATA_FILE)
    model_meta_included, skipped_model_meta = split_model_metadata(model_meta_dict)
    lab_meta_dict = load_lab_metadata(LAB_METADATA_FILE)
    all_data = preprocess_us_hard_data(ANALYSIS_DIR)

    if not all_data:
        print("No data processed. Exiting.")
        sys.exit(0)

    total_records = len(all_data)
    print(f"\nTotal records processed: {total_records}")
    if skipped_model_meta:
        skipped_models = set(skipped_model_meta.keys())
        before = len(all_data)
        all_data = [r for r in all_data if r.get("model") not in skipped_models]
        print(
            f"Applied metadata skip filter: excluded {before - len(all_data)} records from "
            f"{len(skipped_models)} skipped model(s)."
        )

    # Calculate summaries - check for failure (missing metadata)
    skipped_model_ids = set(skipped_model_meta.keys())
    summaries = calculate_summaries(all_data, model_meta_included, skipped_models=skipped_model_ids)
    if summaries is None:
        print("\nAborting preprocessing due to missing model metadata.")
        sys.exit(1) # Exit script if metadata was missing

    # Calculate overall stats
    num_models = len(summaries["model_summary"])
    num_themes = len(summaries["question_theme_summary"])
    valid_models = set(model_meta_included.keys())
    num_judgments = len([i for i in all_data if i["model"] in valid_models])
    num_complete = sum([1 for i in all_data if i["model"] in valid_models and i["compliance"] == "COMPLETE"])

    stats_summary = {"models": num_models, "themes": num_themes, "judgments": num_judgments, "complete": num_complete}
    print("Calculated Stats:", stats_summary)

    # Lab standings (last N months) derived from summary + metadata (rendered only)
    lab_standings = compute_lab_standings(summaries["model_summary"], model_meta_included)

    # Group data by grouping_key for saving individual files (optional)
    data_by_theme = defaultdict(list)
    if not args.no_themes:
        for record in all_data:
            # Only include records for models that HAVE metadata
            if record["model"] in valid_models:
                data_by_theme[record["grouping_key"]].append(record)

    if not args.no_themes:
        num_theme_files = len(data_by_theme)
        print(f"\nPreparing to save {num_theme_files} theme detail files to '{OUTPUT_THEME_DETAIL_DIR}/'.")

        os.makedirs(OUTPUT_THEME_DETAIL_DIR, exist_ok=True)

        saved_files_count = 0
        failed_files_count = 0
        for grouping_key, records in data_by_theme.items():
            safe_filename_key = generate_safe_id(grouping_key)
            output_filename = os.path.join(OUTPUT_THEME_DETAIL_DIR, f"{safe_filename_key}.json.gz")
            if save_theme_detail_file(output_filename, records):
                saved_files_count += 1
            else:
                failed_files_count += 1

        print(f"\nTheme detail file saving complete. Saved: {saved_files_count}, Failed: {failed_files_count}")

        if failed_files_count > 0:
            print("ERROR: Failed to save one or more theme detail files. Aborting metadata generation.")
            sys.exit(1)

    # Phase 1: Save split data artifacts
    # 1) Core metadata (small)
    save_core_metadata(
        OUTPUT_CORE_METADATA_FILE,
        COMPLIANCE_ORDER,
        stats_summary,
        model_meta_included,
        summaries["model_summary"],
        lab_metadata=lab_meta_dict,
    )

    # 2) Question theme summaries (time-binned + all)
    save_question_theme_bins(
        OUTPUT_QTHEME_SUMMARY_DIR,
        summaries["model_theme_summary"],
        model_meta_included,
        summaries["question_theme_summary"],
    )

    # 3) Lab standings for the Lab Standings view (stored in memory for rendering only)

    # 4) Per-model theme breakdowns (lazy-loaded by model detail view)
    save_per_model_theme_breakdowns(OUTPUT_MODEL_THEMES_DIR, summaries["model_theme_summary"])

    # Phase 2: Generate static pages for SEO
    print("\nGenerating static pages (Phase 2)...")
    generate_static_pages(
        model_meta_included,
        summaries,
        data_by_theme,
        lab_standings,
        lab_metadata=lab_meta_dict,
        include_theme_pages=not args.no_themes,
    )
    # Use theme keys from summary (not data_by_theme) so sitemap still includes theme URLs even when skipping regeneration
    theme_keys_for_sitemap = [t.get("grouping_key") for t in summaries["question_theme_summary"] if t.get("grouping_key")]
    lab_keys_for_sitemap = sorted({
        (model_meta_dict.get(m.get("model"), {}) or {}).get("creator")
        for m in summaries["model_summary"]
        if (model_meta_dict.get(m.get("model"), {}) or {}).get("creator", "").strip().lower() not in ("", "unknown")
    })
    generate_sitemap_and_robots(summaries["model_summary"], theme_keys_for_sitemap, lab_keys=lab_keys_for_sitemap, domain_slugs=domain_slugs)
    # Overwrite root About page with static content using real stats
    _write_file("index.html", render_home_page(stats_summary, summaries["question_theme_summary"], lab_standings, lab_metadata=lab_meta_dict, model_summary=summaries["model_summary"]))

    print("\nPreprocessing and saving complete (Phase 1 split outputs).")

if __name__ == "__main__":
    main()
