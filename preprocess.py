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

# --- Configuration ---
ANALYSIS_DIR = "analysis"
MODEL_METADATA_FILE = "model_metadata.json"
OUTPUT_THEME_DETAIL_DIR = "theme_details"  # New directory for theme files
OUTPUT_METADATA_FILENAME = "metadata.json"
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
                        original_question_id = rec.get("question_id", f"unknown_id_{line_num+1}")
                        model = rec.get("model", "unknown_model")
                        compliance = rec.get("compliance", "UNKNOWN").upper()
                        domain = rec.get("domain", "Unknown Domain")
                        question_text = rec.get("question", "")
                        judge_analysis = rec.get("judge_analysis", "")
                        judge_model = rec.get("judge_model", "")
                        timestamp = rec.get("timestamp", "")
                        # Extract new fields for potential use later or reporting
                        api_model = rec.get("api_model", None)
                        original_api_provider = rec.get("original_api_provider", None)


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

                        if compliance == "ERROR":
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
                                "api_model": api_model, # Store original api model name if available
                                "original_api_provider": original_api_provider # Store original provider if available
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

    save_metadata(OUTPUT_METADATA_FILENAME, COMPLIANCE_ORDER, stats_summary, model_meta_dict, summaries)

    print("\nPreprocessing and saving complete.")

if __name__ == "__main__":
    main()
