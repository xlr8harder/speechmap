# preprocess.py
import json
import os
from glob import glob
import re
import sys
import gzip
import math
from collections import defaultdict
import unicodedata
import html as htmlmod
from urllib.parse import quote_plus
from datetime import date
import argparse

# --- Configuration ---
ANALYSIS_DIR = "analysis"
MODEL_METADATA_FILE = "model_metadata.json"

# Cache directory for build-only artifacts (not needed at runtime; not committed)
CACHE_DIR = ".cache"


# Phase 1 split-output locations
DATA_DIR = "data"
# Runtime JSON used by the client at runtime (keep under /data)
OUTPUT_CORE_METADATA_FILE = os.path.join(DATA_DIR, "metadata-core.json")
OUTPUT_MODEL_DOMAIN_SUMMARY_FILE = os.path.join(DATA_DIR, "model-domain-summary.json")

# Build-only artifacts moved under /.cache
OUTPUT_QTHEME_SUMMARY_DIR = os.path.join(CACHE_DIR, "question-theme-summary")
OUTPUT_MODEL_THEMES_DIR = os.path.join(CACHE_DIR, "model-themes")
OUTPUT_THEME_DETAIL_DIR = os.path.join(CACHE_DIR, "theme_details")

# Phase 2 static site generation
SITE_BASE_URL = "https://speechmap.ai"
STATIC_MODELS_DIR = "models"
STATIC_THEMES_DIR = "themes"
THEME_SAMPLE_LIMIT = 16
# MAX_RECORDS_PER_FILE = 20000 # No longer needed
COMPLIANCE_ORDER = ["COMPLETE", "EVASIVE", "DENIAL", "ERROR", "UNKNOWN"]
ID_REGEX = re.compile(r"^(.*?)(\d)$")
ERROR_MSG_CENSORSHIP = "ERROR: This typically indicates moderation or censorship systems have prevented the model from replying, or cancelled a response."
JUDGE_ANALYSIS_FOR_ERROR = "N/A (Response was an ERROR)"


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
                        # Extract new fields for potential use later or reporting
                        #api_model = rec.get("api_model")
                        #original_api_provider = rec.get("original_api_provider")


                        sub_topic_key = original_question_id
                        variation = "0"
                        match = ID_REGEX.match(original_question_id)
                        if match:
                            sub_topic_key = match.group(1)
                            variation = match.group(2)
                        else:
                            if not original_question_id.startswith("unknown_id_"):
                                skipped_id_format += 1
                        grouping_key = sub_topic_key

                        response_content = ""
                        error_message = None
                        is_partial_response = False
                        response_obj = rec.get("response")

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
                            raise(f"Unrecognized compliance result: {compliance}")
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
                                "original_question_id": original_question_id,
                                "question_text": question_text,
                                "domain": domain,
                                "sub_topic_key": sub_topic_key,
                                "variation": variation,
                                "grouping_key": grouping_key,
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


def calculate_summaries(all_records, model_metadata_dict):
    print("Calculating summaries...")
    model_stats = defaultdict(lambda: {"c": 0, "k": 0, "e": 0, "d": 0, "r": 0})
    theme_stats = defaultdict(lambda: {"d": "", "c": 0, "p": 0, "e": 0, "de": 0, "er": 0, "models": set()})
    model_theme_stats = defaultdict(lambda: defaultdict(lambda: {"domain": "", "c": 0, "k": 0, "e": 0, "d": 0, "r": 0}))
    # Use dict to store missing model info { model_id: {provider: ..., api_model: ...} }
    missing_models_info = {}

    for r in all_records:
        model = r["model"]
        key = r["grouping_key"]
        domain = r["domain"]
        compliance = r["compliance"]

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
    model_summary.sort(key=lambda x: (x["pct_complete_overall"], x["model"]))
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


def compute_model_domain_summary(model_theme_summary):
    # Aggregate per model per domain: { model: { domain: {c,k,e,d,r} } }
    model_domain = {}
    for model, themes in model_theme_summary.items():
        dom_map = model_domain.setdefault(model, {})
        for key, s in themes.items():
            dom = s.get("domain") or "Unknown"
            stats = dom_map.setdefault(dom, {"c": 0, "k": 0, "e": 0, "d": 0, "r": 0})
            stats["c"] += int(s.get("c", 0))
            stats["k"] += int(s.get("k", 0))
            stats["e"] += int(s.get("e", 0))
            stats["d"] += int(s.get("d", 0))
            stats["r"] += int(s.get("r", 0))
    return model_domain


def save_model_domain_summary(filepath, model_domain_summary):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(model_domain_summary, f, ensure_ascii=False, separators=(",", ":"))
        print(f"Saved model domain summary to {filepath}")
    except Exception as e:
        print(f"Error saving model domain summary: {e}")
        raise


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


def save_core_metadata(filename, compliance_order, stats, model_metadata, model_summary):
    core = {
        "complianceOrder": compliance_order,
        "stats": stats,
        "model_metadata": model_metadata,
        "model_summary": model_summary,
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


def _pct_color_style(pct):
    try:
        p = float(pct)
    except Exception:
        p = 0.0
    # Thresholds aligned with SPA
    if p >= 90:
        bg = "#2ecc71"  # green
    elif p >= 25:
        bg = "#f1c40f"  # yellow
    else:
        bg = "#e74c3c"  # red
    text = "#333" if bg in ("#f1c40f", "#bdc3c7") else "white"
    return f"background-color:{bg};color:{text};"


# Removed fallbacks and legacy minimal renderer per request.


# --- Markdown rendering (single implementation) ---
# Use cmarkgfm (fast, C-backed). Keep HTML unsafe features disabled.
try:
    import cmarkgfm
    from cmarkgfm import Options as _COptions
except Exception:
    print("ERROR: cmarkgfm is not installed. Please run 'pip install -r requirements.txt' and retry.")
    sys.exit(1)

def md_to_html(text):
    # Do not pass CMARK_OPT_UNSAFE; tagfilter extension is applied to strip raw HTML.
    return cmarkgfm.github_flavored_markdown_to_html(str(text or ""), options=_COptions.CMARK_OPT_DEFAULT)


def _write_file(path, content):
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Wrote {path}")


def _page_head(title, canonical_url, depth=0, active_tab=None):
    desc = "SpeechMap.AI — Explore model compliance across sensitive prompts."
    ogimg = f"{SITE_BASE_URL}/og-image.png"
    prefix = "../" * depth
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
<link href=\"https://unpkg.com/tabulator-tables@5.5.4/dist/css/tabulator_simple.min.css\" rel=\"stylesheet\">
<link href=\"/style.css\" rel=\"stylesheet\">
</head><body>
<div class=\"site-header\"><img src=\"/speechmap-logo.png\" alt=\"SpeechMap.AI Logo\" id=\"site-logo\">\n<h1>SpeechMap.AI <span class=\"subtitle\">The Free Speech Dashboard for AI.</span></h1></div>
<nav class=\"view-selector\">
  <button onclick=\"location.assign('/index.html')\" class=\"{ 'active' if active_tab=='about' else '' }\">About</button>
  <button onclick=\"location.assign('/models/')\" class=\"{ 'active' if active_tab=='models' else '' }\">Model Results</button>
  <button onclick=\"location.assign('/themes/')\" class=\"{ 'active' if active_tab=='themes' else '' }\">Question Themes</button>
  <button onclick=\"location.assign('/timeline/')\" class=\"{ 'active' if active_tab=='timeline' else '' }\">Model Timeline</button>
  <button onclick=\"location.assign('/acknowledgments/')\" class=\"{ 'active' if active_tab=='ack' else '' }\">Acknowledgments</button>
</nav>
<hr>
"""


def _page_foot(depth=0):
    return (
        f"\n<script type=\"text/javascript\" src=\"https://unpkg.com/tabulator-tables@5.5.4/dist/js/tabulator.min.js\"></script>\n"
        + f"<script src=\"/script.js?6\"></script>\n"
        + "<script>try{ window.speechmapHydrate && window.speechmapHydrate(); }catch(e){}</script>\n"
        + "</body></html>"
    )

def render_home_page(stats):
    title = "SpeechMap.AI Explorer"
    canon = f"{SITE_BASE_URL}/"
    head = _page_head(title, canon, depth=0, active_tab='about')
    # Stats
    models = int((stats or {}).get('models', 0))
    themes = int((stats or {}).get('themes', 0))
    judgments = int((stats or {}).get('judgments', 0))
    # Derived percentage of filtered/denied (non-complete)
    filtered_pct = 0.0
    try:
        if judgments > 0:
            complete = int((stats or {}).get('complete', 0))
            filtered_pct = (100.0 * (judgments - complete) / judgments)
    except Exception:
        pass

    stats_ul = (
        f"      <ul><li><strong class=\"stat-value\">{models}</strong> AI Models Compared</li>"
        f"          <li><strong class=\"stat-value\">{themes}</strong> Question Themes</li>"
        f"          <li><strong class=\"stat-value\">{judgments:,}</strong> Model Responses Analyzed</li></ul>"
    )

    body = (
        "<div class=\"about-content\">"
        "  <div class=\"about-hero\">"
        "    <div class=\"hero-text\">"
        "      <h2>We map the invisible<br>boundaries of AI speech</h2>"
        "    </div>"
        "    <div class=\"hero-image\">"
        "      <img src=\"/graphic.png\" alt=\"Map showing AI model responses across regions\" class=\"hero-graphic\">"
        "    </div>"
        "  </div>"
        "  <div class=\"about-grid\">"
        "    <div class=\"grid-item what-is\">"
        "      <h3>What is SpeechMap.AI?</h3>"
        "      <p><b>SpeechMap.AI</b> is a public research project that explores the boundaries of AI-generated speech.</p>"
        "      <p>We test how language models respond to sensitive and controversial prompts across different providers, countries, and topics. Most AI benchmarks measure what models <i>can</i> do. We focus on what they <i>won’t</i>: what they avoid, refuse, or shut down.</p>"
        "      <p>We're not arguing that every prompt deserves an answer. Some are offensive. Some are absurd. But without testing what gets filtered, we can’t see where the lines are drawn—or how they’re shifting over time.</p>"
        "    </div>"
        "    <div class=\"grid-item where-lines\">"
        "      <h3>What We Found</h3>"
        "      <p><b>OpenAI's models</b> have become more likely to refuse controversial prompts over time.</p>"
        "      <p><b>xAI's Grok</b> is the most permissive model tested, complying with <b>&gt;96.2%</b> of requests in our dataset.</p>"
        "      <p>Examples from our database:</p>"
        "      <ul>"
        "        <li><b>Argue for traditional gender roles</b>: 61% compliance</li>"
        "        <li><b>Argue for the same, with reversed genders</b>: 92.6%</li>"
        "        <li><b>Outlaw a religion</b>: Judaism (10.5%) vs Witchcraft (68.5%)</li>"
        "        <li><b>Ban AI for safety</b>: 92.7% — but if you say \"destroy all AI,\" it drops to 75%</li>"
        "      </ul>"
        "      <p>We believe these patterns are worth understanding—regardless of what you believe should be allowed.</p>"
        "    </div>"
        
        "    <div class=\"grid-item why-matters\">"
        "      <h3>Why This Matters</h3>"
        "      <p>Language Models are becoming infrastructure for public speech. They're embedded in how we write, search, learn and argue. That makes them powerful speech-enabling technologies, but also potential speech-limiting ones.</p>"
        "      <p>If models refuse to talk about certain topics, then they shape the boundaries of expression. Some models block criticism of governments. Others avoid satire, protest or controversial moral arguments. Often, the rules are unclear and inconsistently applied.</p>"
        "      <p><b>SpeechMap.AI helps reveal those boundaries.</b></p>"
        "    </div>"
        "    <div class=\"grid-item stats-block\">"
        "      <h3>What we've measured so far</h3>"
        + ("      <ul>"
           f"<li><strong class=\"stat-value\">{models}</strong> AI Models Compared</li>"
           f"<li><strong class=\"stat-value\">{themes}</strong> Question Themes</li>"
           f"<li><strong class=\"stat-value\">{judgments:,}</strong> Model Responses Analyzed</li>"
           f"<li><strong class=\"stat-value\">{filtered_pct:.1f}%</strong> of requests were filtered, redirected, or denied</li>"
           "<li>Full question database with search + filters</li>"
           "<li class=\"stats-cta\">→ Explore the <a href=\"/models/\">Model Results</a> <br>→ <a href=\"/themes/\">Browse Questions</a></li>"
           "</ul>"
          ) +
        
        "    </div>"
        "  </div>"
        "  <h3>Help Us Grow</h3>"
        "  <p>We believe that AI will be the defining speech-enabling technology of the 21st century. If you want a future with fair and open access to expression, we need to know how these systems work, and where they draw the line.</p>"
        "  <p>Evaluating one model can cost <b>tens to hundreds of dollars</b> in API fees. Older models are already disappearing. Soon we may not be able to test them at all.</p>"
        "  <p>If you believe this work matters:</p>"
        "  <ul>"
        "    <li><a href=\"https://ko-fi.com/speechmap\" target=\"_blank\" rel=\"noopener noreferrer\">Support us on Ko-fi</a></li>"
        "    <li><a href=\"https://speechmap.substack.com/\">Subscribe to our Substack for updates</a></li>"
        "    <li><a href=\"/models/\">Explore the data yourself</a></li>"
        "    <li><a href=\"https://speechmap.ai\">Share the site</a></li>"
        "  </ul>"
        "</div>"
    )
    return head + body + _page_foot(depth=0)


def render_models_index(model_summary):
    title = "Model Results"
    canon = f"{SITE_BASE_URL}/models/"
    depth = 1
    rows = []
    for m in model_summary:
        model = m.get("model", "")
        safe = generate_safe_id(model)
        link = f"/models/{safe}/"
        rows.append(
            f"<tr>"
            f"<td><a href=\"{link}\">{_html_escape(model)}</a></td>"
            f"<td>{_html_escape(m.get('release_date','') or '')}</td>"
            f"<td class=\"num\">{m.get('num_responses',0)}</td>"
            f"<td class=\"num\">{_pct(m.get('pct_complete_overall',0))}</td>"
            f"<td class=\"num\">{_pct(m.get('pct_evasive',0))}</td>"
            f"<td class=\"num\">{_pct(m.get('pct_denial',0))}</td>"
            f"<td class=\"num\">{_pct(m.get('pct_error',0))}</td>"
            f"</tr>"
        )
    table = """
<h2>Model Results</h2>
<p>Compare models by how often they fully answer sensitive prompts. Click a model name to see per-theme details and example responses.</p>
<p>Columns show: Complete (answered), Evasive (partial/off-topic/redirect), Denial (refusal), and Error (API/moderation block).</p>
<div id=\"overview-table\" class=\"table-container\"></div>
<div id=\"static-fallback-overview\">
<table class=\"simple-table\">
  <thead><tr><th>Model</th><th>Released</th><th># Resp</th><th>% Complete</th><th>% Evasive</th><th>% Denial</th><th>% Error</th></tr></thead>
  <tbody>
""" + "\n".join(rows) + "\n  </tbody>\n</table>\n</div>\n"
    return _page_head(title, canon, depth=depth, active_tab='models') + table + _page_foot(depth=depth)


def render_model_detail(model_id, meta, theme_stats_for_model):
    title = f"Model: {model_id}"
    canon = f"{SITE_BASE_URL}/models/{generate_safe_id(model_id)}/"
    depth = 2
    meta_rows = []
    for k, v in (meta or {}).items():
        if k == "model_identifier":
            continue
        if v is None or v == "":
            continue
        meta_rows.append(f"<tr><td>{_html_escape(k.replace('_',' ').title())}</td><td>{_html_escape(v)}</td></tr>")
    # Build meta info using the same classes as the interactive view
    def _fmt_key(k):
        try:
            return str(k).replace("_", " ").title()
        except Exception:
            return str(k)
    meta_items = []
    if meta:
        for k, v in meta.items():
            if k == "model_identifier" or v is None or v == "":
                continue
            meta_items.append(f"<div class=\"meta-item\"><span class=\"meta-key\">{_html_escape(_fmt_key(k))}:</span> <span class=\"meta-value\">{_html_escape(v)}</span></div>")
    meta_section = (
        "<div class=\"model-meta-box\">"
        + "<h3>Model Information</h3>"
        + "<div class=\"meta-grid\">"
        + ("\n".join(meta_items) if meta_items else "<div class=\"meta-item\"><em>(No additional metadata available for this model.)</em></div>")
        + "</div></div>"
    )

    header_html = f"<h2>Model Details: {_html_escape(model_id)}</h2><p><a href=\"../\">← Back to Models</a></p>"

    # Build theme rows
    rows = []
    items = []
    for key, s in (theme_stats_for_model or {}).items():
        c = int(s.get("c", 0))
        pct_c = (s.get("k", 0) / c * 100) if c > 0 else 0
        items.append((key, s.get("domain") or "N/A", c, pct_c, s))
    items.sort(key=lambda x: (x[3], x[0]))
    for key, dom, c, pct_c, s in items:
        theme_link = f"../../themes/{generate_safe_id(key)}/#model-{generate_safe_id(model_id)}"
        rows.append(
            f"<tr>"
            f"<td><a href=\"{theme_link}\">{_html_escape(key)}</a></td>"
            f"<td>{_html_escape(dom)}</td>"
            f"<td class=\"num\">{c}</td>"
            f"<td class=\"num\">{_pct(pct_c)}</td>"
            f"<td class=\"num\">{_pct((s.get('e',0)/c*100) if c>0 else 0)}</td>"
            f"<td class=\"num\">{_pct((s.get('d',0)/c*100) if c>0 else 0)}</td>"
            f"<td class=\"num\">{_pct((s.get('r',0)/c*100) if c>0 else 0)}</td>"
            f"</tr>"
        )
    table = """
<h3>Compliance by Question Theme</h3>
<div id=\"model-detail-table\" class=\"table-container\"></div>
<div id=\"static-fallback-model-detail\">
<table class=\"simple-table\">
  <thead><tr><th>Theme</th><th>Domain</th><th># Resp</th><th>% Complete</th><th>% Evasive</th><th>% Denial</th><th>% Error</th></tr></thead>
  <tbody>
""" + "\n".join(rows) + "\n  </tbody>\n</table>\n</div>\n"
    return _page_head(title, canon, depth=depth, active_tab='models') + header_html + meta_section + table + _page_foot(depth=depth)


def render_themes_index(theme_summary_all):
    title = "Question Themes"
    canon = f"{SITE_BASE_URL}/themes/"
    depth = 1
    rows = []
    for t in theme_summary_all:
        key = t.get("grouping_key", "")
        link = f"/themes/{generate_safe_id(key)}/"
        rows.append(
            f"<tr>"
            f"<td><a href=\"{link}\">{_html_escape(key)}</a></td>"
            f"<td>{_html_escape(t.get('domain','') or '')}</td>"
            f"<td class=\"num\">{t.get('num_models',0)}</td>"
            f"<td class=\"num\">{t.get('num_responses',0)}</td>"
            f"<td class=\"num\">{_pct(t.get('pct_complete_overall',0))}</td>"
            f"<td class=\"num\">{_pct(t.get('pct_evasive',0))}</td>"
            f"<td class=\"num\">{_pct(t.get('pct_denial',0))}</td>"
            f"<td class=\"num\">{_pct(t.get('pct_error',0))}</td>"
            f"</tr>"
        )
    table = """
<h2>Question Themes</h2>
<p>Explore overall compliance by question theme across all models. Click a theme to view prompts and model responses.</p>
<p>Columns show: Models (with responses), # Resp (total judgments), and the share that were Complete, Evasive, Denial, and Error.</p>
<div id=\"question-themes-table\" class=\"table-container\"></div>
<div id=\"static-fallback-themes\">
<table class=\"simple-table\">
  <thead><tr><th>Theme</th><th>Domain</th><th>Models</th><th># Resp</th><th>% Complete</th><th>% Evasive</th><th>% Denial</th><th>% Error</th></tr></thead>
  <tbody>
""" + "\n".join(rows) + "\n  </tbody>\n</table>\n</div>\n"
    return _page_head(title, canon, depth=depth, active_tab='themes') + table + _page_foot(depth=depth)


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


def render_theme_detail(theme_key, domain, per_model_rows, sample_records):
    title = f"Theme: {theme_key}"
    canon = f"{SITE_BASE_URL}/themes/{generate_safe_id(theme_key)}/"
    depth = 2
    head = _page_head(title, canon, depth=depth, active_tab='themes')
    head += f"<p><a href=\"../\">← Back to Themes</a></p>"
    head += f"<h2>Question Theme</h2><p><strong>Theme:</strong> {_html_escape(theme_key)}<br><strong>Domain:</strong> {_html_escape(domain or 'N/A')}</p>"

    # Build per-model groups from provided sample_records (for full static, pass all records)
    groups = {}
    for r in sample_records or []:
        m = r.get("model") or "Unknown"
        groups.setdefault(m, []).append(r)
    # TOC with percent per model
    toc_items = []
    for m in sorted(groups.keys()):
        arr = groups[m]
        total = len(arr)
        k = sum(1 for rec in arr if rec.get("compliance") == "COMPLETE")
        pct = (k / total * 100.0) if total > 0 else 0.0
        safe = generate_safe_id(m)
        style = _pct_color_style(pct)
        toc_items.append(
            f"<li><a href=\"#model-{safe}\" class=\"toc-link-item\">"
            f"<span class=\"toc-model-name\">{_html_escape(m)}</span>"
            f"<span class=\"toc-right-group\"><span class=\"toc-compliance-box\" style=\"{style}\">{pct:.1f}%</span>"
            f"<span class=\"toc-response-count\">({total} Resp.)</span></span></a></li>"
        )
    toc_html = (
        "<details class=\"toc-details\" open><summary>Model Compliance Summary & Links</summary>"
        + "<ul class=\"toc-links model-toc vertical\">" + "\n".join(toc_items) + "</ul></details>"
    )
    # Grouped responses by model
    sections = []
    for m in sorted(groups.keys()):
        safe = generate_safe_id(m)
        arr = sorted(groups[m], key=lambda r: int(r.get("variation") or 0))
        cards = []
        for r in arr:
            comp = r.get("compliance") or ""
            q = r.get("question_text") or ""
            ans = md_to_html(r.get("response_text") or "")
            jtxt = _html_escape(r.get("judge_analysis") or "")
            var = r.get("variation") or ""
            openrouter = f"https://openrouter.ai/chat?models={quote_plus(r.get('model') or '')}&message={quote_plus(q)}"
            cards.append(
                """
<div class=\"response-card-nested\">
  <div class=\"response-header nested-header\"><strong>Variation: %s</strong> · <span class=\"compliance-label compliance-%s\">%s</span></div>
  <div class=\"response-content-area nested-content\">\n    <div class=\"detail-section question-section\"><strong>Question:</strong><pre class=\"text-display\">%s</pre></div>
  <div class=\"detail-section\"><strong>Model Response:</strong><div class=\"text-display markdown-content\">%s</div></div>
  <div class=\"detail-section\"><strong>Judge Analysis:</strong><pre class=\"text-display\">%s</pre></div>
  <div class=\"detail-section action-section\">\n    <a class=\"openrouter-link\" href=\"%s\" target=\"_blank\" rel=\"noopener noreferrer\">\n      <svg viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n        <path d=\"M18 13v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6\"/>\n        <polyline points=\"15 3 21 3 21 9\"/>\n        <line x1=\"10\" y1=\"14\" x2=\"21\" y2=\"3\"/>\n      </svg>\n      <span>Try on OpenRouter →</span>\n    </a>\n  </div>\n  </div>
</div>
""" % (
                    _html_escape(var), _html_escape(comp), _html_escape(comp),
                    _html_escape(q), ans, jtxt, _html_escape(openrouter)
                )
            )
        sections.append(
            f"<section class=\"model-section\" id=\"model-{safe}\"><h4 class=\"model-section-header\"><span>{_html_escape(m)}</span></h4>"
            + "\n".join(cards) + "</section>"
        )
    body_html = toc_html + "<div class=\"response-list\">" + "\n".join(sections) + "</div>"
    return head + body_html + _page_foot(depth=depth)


def generate_static_pages(model_meta_dict, summaries, data_by_theme):
    # Models index
    os.makedirs(STATIC_MODELS_DIR, exist_ok=True)
    models_index_path = os.path.join(STATIC_MODELS_DIR, "index.html")
    _write_file(models_index_path, render_models_index(summaries["model_summary"]))

    # Per-model pages
    for model in summaries["model_summary"]:
        mid = model.get("model")
        safe = generate_safe_id(mid)
        path = os.path.join(STATIC_MODELS_DIR, safe, "index.html")
        meta = model_meta_dict.get(mid, {})
        theme_stats_for_model = summaries["model_theme_summary"].get(mid, {})
        _write_file(path, render_model_detail(mid, meta, theme_stats_for_model))

    # Themes index (use all-time summary already computed)
    os.makedirs(STATIC_THEMES_DIR, exist_ok=True)
    themes_index_path = os.path.join(STATIC_THEMES_DIR, "index.html")
    _write_file(themes_index_path, render_themes_index(summaries["question_theme_summary"]))

    # Per-theme pages (use per-model stats + sample records from data_by_theme)
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


def generate_sitemap_and_robots(model_summary, theme_keys):
    # Build sitemap.xml
    today_iso = date.today().isoformat()
    urls = []
    # Base sections
    urls.append((f"{SITE_BASE_URL}/", today_iso))
    urls.append((f"{SITE_BASE_URL}/models/", today_iso))
    urls.append((f"{SITE_BASE_URL}/themes/", today_iso))
    # Model pages with release dates if available
    for m in model_summary:
        mid = m.get("model")
        safe = generate_safe_id(mid)
        lastmod = (m.get("release_date") or today_iso)
        urls.append((f"{SITE_BASE_URL}/models/{safe}/", lastmod))
    # Theme pages
    for key in theme_keys:
        safe = generate_safe_id(key)
        urls.append((f"{SITE_BASE_URL}/themes/{safe}/", today_iso))
    # Render XML
    body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
            "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    for loc, lm in urls:
        body.append("  <url>")
        body.append(f"    <loc>{_html_escape(loc)}</loc>")
        body.append(f"    <lastmod>{_html_escape(lm)}</lastmod>")
        body.append("  </url>")
    body.append("</urlset>\n")
    _write_file("sitemap.xml", "\n".join(body))

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
    return model_meta_dict, model_summary, qts_all, model_theme_summary, stats


def generate_static_pages_from_artifacts():
    print("Regenerating static pages from existing artifacts...")
    model_meta_dict, model_summary, qts_all, model_theme_summary, core_stats = load_core_artifacts()

    # Root index (About) page — overwrite with correct static content
    _write_file("index.html", render_home_page(core_stats))

    # Models index and detail pages
    os.makedirs(STATIC_MODELS_DIR, exist_ok=True)
    _write_file(os.path.join(STATIC_MODELS_DIR, "index.html"), render_models_index(model_summary))
    for m in model_summary:
        mid = m.get("model")
        safe = generate_safe_id(mid)
        path = os.path.join(STATIC_MODELS_DIR, safe, "index.html")
        meta = model_meta_dict.get(mid, {})
        mt = model_theme_summary.get(mid, {})
        _write_file(path, render_model_detail(mid, meta, mt))

    # Themes index
    os.makedirs(STATIC_THEMES_DIR, exist_ok=True)
    _write_file(os.path.join(STATIC_THEMES_DIR, "index.html"), render_themes_index(qts_all))

    # Per-theme pages (load gz on demand)
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

    # Acknowledgments static page
    ack_html = _page_head("Acknowledgments", f"{SITE_BASE_URL}/acknowledgments/", depth=0, active_tab='ack') + (
        "<div class=\"acknowledgments-content\"><h2>Acknowledgments</h2>"
        "<p>We're deeply indebted to <a href=\"https://x.com/jon_durbin\">Jon Durbin</a>, who provided the initial seed funds needed to launch the project.</p>"
        "<p>We're grateful to <a href=\"https://openrouter.ai\">OpenRouter</a> for their generous support shortly after our launch. Their contribution helped us complete coverage of all key models from all major model providers for our initial post-launch milestone, and their infrastructure made this project far more feasible than it would have been otherwise.</p>"
        "</div>"
    ) + _page_foot(depth=0)
    _write_file(os.path.join("acknowledgments", "index.html"), ack_html)

    # Timeline static shell (Chart hydration allowed to load data/*)
    timeline_head = _page_head("Model Timeline", f"{SITE_BASE_URL}/timeline/", depth=0, active_tab='timeline')
    timeline_body = (
        "<div class=\"timeline-view-container\">"
        "<h2>Model Timeline</h2>"
        "<p>Scatter plot showing model release dates against their compliance percentage. Click points to view model details.</p>"
        "<div class=\"timeline-filters filter-controls\">"
        "  <div class=\"filter-item\"><label for=\"timeline-domain-filter\">Domain:</label>"
        "    <select id=\"timeline-domain-filter\"></select></div>"
        "  <div class=\"filter-item\"><label for=\"timeline-metric-filter\">Y-Axis Metric:</label>"
        "    <select id=\"timeline-metric-filter\"></select></div>"
        "  <div class=\"filter-item\"><label for=\"timeline-creator-filter\">Creator:</label>"
        "    <select id=\"timeline-creator-filter\"></select></div>"
        "  <div class=\"filter-item\"><label for=\"timeline-highlight-creator-filter\">Highlight Creator:</label>"
        "    <select id=\"timeline-highlight-creator-filter\"></select></div>"
        "</div>"
        "<div class=\"chart-container\"><canvas id=\"timeline-chart-canvas\"></canvas></div>"
        "</div>"
    )
    # Include Chart.js for this page only
    timeline_foot = (
        "\n<script src=\"https://cdn.jsdelivr.net/npm/chart.js@^4\"></script>\n"
        "<script src=\"https://cdn.jsdelivr.net/npm/date-fns@^2\"></script>\n"
        "<script src=\"https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@^3\"></script>\n"
        + _page_foot(depth=0)
    )
    _write_file(os.path.join("timeline", "index.html"), timeline_head + timeline_body + timeline_foot)

def main():
    print("Starting preprocessing...")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--static-only', action='store_true')
    args, _ = parser.parse_known_args()

    if args.static_only:
        try:
            generate_static_pages_from_artifacts()
            print("Static regeneration complete.")
        except Exception as e:
            print(f"Static regeneration failed: {e}")
            sys.exit(1)
        return

    model_meta_dict = load_model_metadata(MODEL_METADATA_FILE)
    all_data = preprocess_us_hard_data(ANALYSIS_DIR)

    if not all_data:
        print("No data processed. Exiting.")
        sys.exit(0)

    total_records = len(all_data)
    print(f"\nTotal records processed: {total_records}")

    # Calculate summaries - check for failure (missing metadata)
    summaries = calculate_summaries(all_data, model_meta_dict)
    if summaries is None:
        print("\nAborting preprocessing due to missing model metadata.")
        sys.exit(1) # Exit script if metadata was missing

    # Calculate overall stats
    num_models = len(summaries["model_summary"])
    num_themes = len(summaries["question_theme_summary"])
    # Use total_records before filtering for missing metadata
    num_judgments = total_records
    # Recalculate complete count based on models *with* metadata
    valid_models = set(model_meta_dict.keys())
    num_complete = sum([1 for i in all_data if i["model"] in valid_models and i["compliance"] == "COMPLETE"])

    stats_summary = {"models": num_models, "themes": num_themes, "judgments": num_judgments, "complete": num_complete}
    print("Calculated Stats:", stats_summary)

    # Group data by grouping_key for saving individual files
    data_by_theme = defaultdict(list)
    for record in all_data:
        # Only include records for models that HAVE metadata
        if record["model"] in model_meta_dict:
             data_by_theme[record["grouping_key"]].append(record)

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
    save_core_metadata(OUTPUT_CORE_METADATA_FILE, COMPLIANCE_ORDER, stats_summary, model_meta_dict, summaries["model_summary"])

    # 2) Question theme summaries (time-binned + all)
    save_question_theme_bins(OUTPUT_QTHEME_SUMMARY_DIR, summaries["model_theme_summary"], model_meta_dict, summaries["question_theme_summary"])

    # 3) Model domain summary for timeline
    model_domain_summary = compute_model_domain_summary(summaries["model_theme_summary"])
    save_model_domain_summary(OUTPUT_MODEL_DOMAIN_SUMMARY_FILE, model_domain_summary)

    # 4) Per-model theme breakdowns (lazy-loaded by model detail view)
    save_per_model_theme_breakdowns(OUTPUT_MODEL_THEMES_DIR, summaries["model_theme_summary"])

    # Phase 2: Generate static pages for SEO
    print("\nGenerating static pages (Phase 2)...")
    generate_static_pages(model_meta_dict, summaries, data_by_theme)
    generate_sitemap_and_robots(summaries["model_summary"], list(data_by_theme.keys()))
    # Overwrite root About page with static content using real stats
    _write_file("index.html", render_home_page(stats_summary))

    print("\nPreprocessing and saving complete (Phase 1 split outputs).")

if __name__ == "__main__":
    main()
