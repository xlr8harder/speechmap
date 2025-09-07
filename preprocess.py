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
from urllib.parse import quote_plus
from datetime import date

# --- Configuration ---
ANALYSIS_DIR = "analysis"
MODEL_METADATA_FILE = "model_metadata.json"
OUTPUT_THEME_DETAIL_DIR = "theme_details"  # New directory for theme files
OUTPUT_METADATA_FILENAME = "metadata.json"  # Legacy, no longer written in Phase 1

# Phase 1 split-output locations
DATA_DIR = "data"
OUTPUT_CORE_METADATA_FILE = os.path.join(DATA_DIR, "metadata-core.json")
OUTPUT_QTHEME_SUMMARY_DIR = os.path.join(DATA_DIR, "question-theme-summary")
OUTPUT_MODEL_THEMES_DIR = os.path.join(DATA_DIR, "model-themes")
OUTPUT_MODEL_DOMAIN_SUMMARY_FILE = os.path.join(DATA_DIR, "model-domain-summary.json")

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


def _write_file(path, content):
    dirpath = os.path.dirname(path)
    if dirpath:
        os.makedirs(dirpath, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Wrote {path}")


def _page_head(title, canonical_url, depth=0):
    desc = "SpeechMap.AI — Explore model compliance across sensitive prompts."
    # Use absolute OG image for social sharing
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
<link href=\"{prefix}style.css\" rel=\"stylesheet\">
</head><body>
<div class=\"site-header\"><a href=\"{prefix}\"><img src=\"{prefix}speechmap-logo.png\" alt=\"SpeechMap.AI Logo\" id=\"site-logo\"></a>
<h1><a href=\"{prefix}\" style=\"text-decoration:none;color:inherit\">SpeechMap.AI</a></h1></div>
<nav class=\"view-selector\">
  <a href=\"{prefix}index.html#/overview\">Interactive Results</a>
  <a href=\"{prefix}models/\">Models (Static)</a>
  <a href=\"{prefix}themes/\">Themes (Static)</a>
</nav>
<hr>
"""


def _page_foot():
    return """<footer style=\"margin:30px 0;color:#666;font-size:0.9em\">Static render for SEO. For full interactivity, use the Interactive Results.
</footer></body></html>"""


def render_models_index(model_summary):
    title = "Model Results (Static)"
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
<p>This is a static, indexable version. For interactive sorting/filtering, use the Interactive Results.</p>
<table class=\"simple-table\">
  <thead><tr><th>Model</th><th>Released</th><th># Resp</th><th>% Complete</th><th>% Evasive</th><th>% Denial</th><th>% Error</th></tr></thead>
  <tbody>
""" + "\n".join(rows) + "\n  </tbody>\n</table>\n"
    return _page_head(title, canon, depth=depth) + table + _page_foot()


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
    meta_html = """
<h2>Model Details</h2>
<p><a href=\"../\">← Back to Models</a> · <a href=\"%sindex.html#/model/%s\">Open Interactive</a></p>
<table class=\"simple-table\"><tbody>
%s
</tbody></table>
""" % ("../" * (depth), quote_plus(model_id), "\n".join(meta_rows) or "<tr><td colspan=2><em>No additional metadata.</em></td></tr>")

    # Build theme rows
    rows = []
    items = []
    for key, s in (theme_stats_for_model or {}).items():
        c = int(s.get("c", 0))
        pct_c = (s.get("k", 0) / c * 100) if c > 0 else 0
        items.append((key, s.get("domain") or "N/A", c, pct_c, s))
    items.sort(key=lambda x: (x[3], x[0]))
    for key, dom, c, pct_c, s in items:
        theme_link = f"../../themes/{generate_safe_id(key)}/"
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
<table class=\"simple-table\">
  <thead><tr><th>Theme</th><th>Domain</th><th># Resp</th><th>% Complete</th><th>% Evasive</th><th>% Denial</th><th>% Error</th></tr></thead>
  <tbody>
""" + "\n".join(rows) + "\n  </tbody>\n</table>\n"
    return _page_head(title, canon, depth=depth) + meta_html + table + _page_foot()


def render_themes_index(theme_summary_all):
    title = "Question Themes (Static)"
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
<p>Static, indexable list for search engines. For dynamic filtering or per-model views, use the Interactive Results.</p>
<table class=\"simple-table\">
  <thead><tr><th>Theme</th><th>Domain</th><th>Models</th><th># Resp</th><th>% Complete</th><th>% Evasive</th><th>% Denial</th><th>% Error</th></tr></thead>
  <tbody>
""" + "\n".join(rows) + "\n  </tbody>\n</table>\n"
    return _page_head(title, canon, depth=depth) + table + _page_foot()


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
    head = _page_head(title, canon, depth=depth)
    head += f"<p><a href=\"../\">← Back to Themes</a> · <a href=\"{'../' * depth}index.html#/questions/{quote_plus(theme_key)}\">Open Interactive</a></p>"
    head += f"<h2>Question Theme</h2><p><strong>Theme:</strong> {_html_escape(theme_key)}<br><strong>Domain:</strong> {_html_escape(domain or 'N/A')}</p>"

    # Per-model summary table
    rows_html = []
    for model, dom, c, pct_c, s in per_model_rows:
        model_link = f"../../models/{generate_safe_id(model)}/"
        rows_html.append(
            f"<tr><td><a href=\"{model_link}\">{_html_escape(model)}</a></td>"
            f"<td>{_html_escape(dom)}</td>"
            f"<td class=\"num\">{c}</td>"
            f"<td class=\"num\">{_pct(pct_c)}</td>"
            f"<td class=\"num\">{_pct((s.get('e',0)/c*100) if c>0 else 0)}</td>"
            f"<td class=\"num\">{_pct((s.get('d',0)/c*100) if c>0 else 0)}</td>"
            f"<td class=\"num\">{_pct((s.get('r',0)/c*100) if c>0 else 0)}</td></tr>"
        )
    table = """
<h3>Models Summary</h3>
<table class=\"simple-table\">
 <thead><tr><th>Model</th><th>Domain</th><th># Resp</th><th>% Complete</th><th>% Evasive</th><th>% Denial</th><th>% Error</th></tr></thead>
 <tbody>
""" + "\n".join(rows_html) + "\n </tbody>\n</table>\n"

    # Sample responses
    cards = []
    for r in sample_records:
        model = r.get("model")
        comp = r.get("compliance")
        q = r.get("question_text") or ""
        ans = r.get("response_text") or ""
        jtxt = r.get("judge_analysis") or ""
        var = r.get("variation") or ""
        openrouter = f"https://openrouter.ai/chat?models={quote_plus(model or '')}&message={quote_plus(q)}"
        cards.append(
            """
<div class=\"response-card-nested\">
  <div class=\"response-header nested-header\"><strong>Variation: %s</strong> · <span class=\"compliance-label\">%s</span></div>
  <div class=\"detail-section question-section\"><strong>Question:</strong><pre class=\"text-display\">%s</pre></div>
  <div class=\"detail-section\"><strong>Model Response:</strong><pre class=\"text-display\">%s</pre></div>
  <div class=\"detail-section\"><strong>Judge Analysis:</strong><pre class=\"text-display\">%s</pre></div>
  <div><a class=\"openrouter-link\" href=\"%s\" target=\"_blank\" rel=\"noopener noreferrer\">Try on OpenRouter →</a></div>
</div>
""" % (_html_escape(var), _html_escape(comp), _html_escape(q), _html_escape(ans[:2000]), _html_escape(jtxt[:2000]), _html_escape(openrouter))
        )
    sample_html = "<h3>Sample Responses</h3>" + "\n".join(cards)

    return head + table + sample_html + _page_foot()


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
        sample = _theme_sample_from_records(records, THEME_SAMPLE_LIMIT)
        _write_file(path, render_theme_detail(theme_key, domain_guess, per_model_rows, sample))


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

def main():
    print("Starting preprocessing...")
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

    print("\nPreprocessing and saving complete (Phase 1 split outputs).")

if __name__ == "__main__":
    main()
