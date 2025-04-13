import json
import os
from glob import glob
import re
import sys
import gzip
import math
from collections import defaultdict

# --- Configuration ---
ANALYSIS_DIR = "analysis"
MODEL_METADATA_FILE = "model_metadata.json"
OUTPUT_DATA_BASE_FILENAME = "speechdata"
OUTPUT_METADATA_FILENAME = "metadata.json"
MAX_RECORDS_PER_FILE = 20000
COMPLIANCE_ORDER = ['COMPLETE', 'EVASIVE', 'DENIAL', 'ERROR', 'UNKNOWN']
ID_REGEX = re.compile(r"^(.*?)(\d)$")
ERROR_MSG_CENSORSHIP = "ERROR: This typically indicates moderation or censorship systems have prevented the model from replying, or cancelled a response."
JUDGE_ANALYSIS_FOR_ERROR = "N/A (Response was an ERROR)"

def generate_safe_id(text):
    text_str = str(text) if text is not None else ''
    safe_text = re.sub(r'[^\w\s-]', '', text_str.lower())
    safe_text = re.sub(r'\s+', '-', safe_text)
    safe_text = safe_text.strip('-')
    return safe_text if safe_text else "id"

def load_model_metadata(filepath):
    metadata = {}
    if not os.path.exists(filepath):
        print(f"Warning: Model metadata file not found: {filepath}")
        return metadata

    print(f"Loading model metadata from {filepath}...")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
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
    if not file_paths: print(f"Warning: No 'compliance_us_hard_*.jsonl' files found."); return []

    processed_count = 0; error_count = 0; skipped_id_format = 0

    for i, fpath in enumerate(file_paths):
        fname = os.path.basename(fpath)
        print(f"Processing file ({i+1}/{len(file_paths)}): {fname}")
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f):
                    rec = None
                    try:
                        rec = json.loads(line.strip())
                        original_question_id = rec.get('question_id', f'unknown_id_{line_num+1}')
                        model = rec.get('model', 'unknown_model'); timestamp = rec.get('timestamp', '')
                        compliance = rec.get('compliance', 'UNKNOWN').upper()
                        domain = rec.get('domain', 'Unknown Domain')
                        question_text = rec.get('question', '')
                        judge_analysis = rec.get('judge_analysis', '')
                        judge_model = rec.get('judge_model', '')

                        sub_topic_key = original_question_id; variation = '0'
                        match = ID_REGEX.match(original_question_id)
                        if match:
                            sub_topic_key = match.group(1)
                            variation = match.group(2)
                        else:
                             if not original_question_id.startswith('unknown_id_'):
                                # print(f"    Warn: QID format '{original_question_id}' mismatch ln {line_num+1}. Using defaults.") # Reduce noise
                                skipped_id_format += 1
                        grouping_key = sub_topic_key

                        response_content = ""; error_message = None; is_partial_response = False
                        response_obj = rec.get('response')

                        if compliance == 'ERROR':
                            is_partial_response = True
                            if not judge_analysis: judge_analysis = JUDGE_ANALYSIS_FOR_ERROR
                            specific_api_error = "(Specific API error details missing)"
                            if isinstance(response_obj, dict) and response_obj.get('choices'):
                                choice = response_obj['choices'][0]
                                if isinstance(choice.get('message'), dict): response_content = choice['message'].get('content', '')
                                if isinstance(choice.get('error'), dict): specific_api_error = choice['error'].get('message', 'Unknown API error structure')
                            error_message = ERROR_MSG_CENSORSHIP
                            if specific_api_error and specific_api_error != 'Unknown API error structure':
                                 error_message += f" [API Msg: {specific_api_error}]"

                        elif isinstance(response_obj, dict) and response_obj.get('choices'):
                            choice = response_obj['choices'][0]
                            if isinstance(choice.get('message'), dict): response_content = choice['message'].get('content', '')
                            if isinstance(choice.get('error'), dict):
                                # print(f"    Warn: API error ln {line_num+1} but compliance='{compliance}'. Forcing ERROR.") # Reduce noise
                                compliance = 'ERROR'; is_partial_response = True; error_count += 1 # Count as error
                                specific_api_error = choice['error'].get('message', 'Unknown API error structure')
                                error_message = ERROR_MSG_CENSORSHIP
                                if specific_api_error and specific_api_error != 'Unknown API error structure':
                                      error_message += f" [API Msg: {specific_api_error}]"
                                if not judge_analysis: judge_analysis = JUDGE_ANALYSIS_FOR_ERROR

                        if compliance not in COMPLIANCE_ORDER: compliance = 'UNKNOWN'

                        safe_model_id_part = generate_safe_id(model)
                        record_id = f"{model}-{original_question_id}-{timestamp}"
                        anchor_id = f"response-{safe_model_id_part}"

                        # Only include fields needed for summaries if optimizing further,
                        # but for now keep all fields for simplicity in calculating summaries later
                        all_records.append({
                            'id': record_id, 'anchor_id': anchor_id, 'model': model, 'timestamp': timestamp,
                            'compliance': compliance,
                            # Exclude large text fields initially if needed? No, need them for calculation later.
                            'response_text': response_content, 'judge_analysis': judge_analysis,
                            'judge_model': judge_model, 'error_message': error_message, 'is_partial_response': is_partial_response,
                            'original_question_id': original_question_id, 'question_text': question_text,
                            'domain': domain, 'sub_topic_key': sub_topic_key, 'variation': variation,
                            'grouping_key': grouping_key
                        })
                        processed_count += 1
                    except Exception as e: print(f"    ERR Proc Line {line_num+1} in {fname}: {e} - Rec: {rec}"); error_count += 1
        except Exception as e: print(f"  ERR Reading File {fname}: {e}"); error_count += 1

    print(f"\nPreprocessing finished. Processed: {processed_count}, Skipped Format: {skipped_id_format}, Errors: {error_count}")
    return all_records

def calculate_summaries(all_records, model_metadata_dict):
    """Calculates model and question theme summaries from all records."""
    print("Calculating summaries...")
    # Model Summary Calculation
    model_stats = defaultdict(lambda: {"c": 0, "k": 0, "e": 0, "d": 0, "r": 0})
    for r in all_records:
        model = r['model']
        model_stats[model]["c"] += 1
        if r['compliance'] == 'COMPLETE': model_stats[model]["k"] += 1
        elif r['compliance'] == 'EVASIVE': model_stats[model]["e"] += 1
        elif r['compliance'] == 'DENIAL': model_stats[model]["d"] += 1
        elif r['compliance'] == 'ERROR': model_stats[model]["r"] += 1

    model_summary = []
    for model, stats in model_stats.items():
        count = stats["c"]
        release_date = model_metadata_dict.get(model, {}).get("release_date", None)
        model_summary.append({
            "model": model,
            "num_responses": count,
            "pct_complete_overall": (stats["k"] / count * 100) if count > 0 else 0,
            "pct_evasive": (stats["e"] / count * 100) if count > 0 else 0,
            "pct_denial": (stats["d"] / count * 100) if count > 0 else 0,
            "pct_error": (stats["r"] / count * 100) if count > 0 else 0,
            "release_date": release_date
        })
    # Default sort by compliance ascending, then model name
    model_summary.sort(key=lambda x: (x["pct_complete_overall"], x["model"]))
    print(f"Calculated summary for {len(model_summary)} models.")

    # Question Theme Summary Calculation
    theme_stats = defaultdict(lambda: {"d": "", "c": 0, "p": 0, "e": 0, "de": 0, "er": 0, "models": set()})
    for r in all_records:
        key = r['grouping_key']
        theme_stats[key]["c"] += 1
        theme_stats[key]["models"].add(r['model'])
        theme_stats[key]["d"] = r['domain'] # Assume domain is consistent for a key
        if r['compliance'] == 'COMPLETE': theme_stats[key]["p"] += 1
        elif r['compliance'] == 'EVASIVE': theme_stats[key]["e"] += 1
        elif r['compliance'] == 'DENIAL': theme_stats[key]["de"] += 1
        elif r['compliance'] == 'ERROR': theme_stats[key]["er"] += 1

    question_theme_summary = []
    for key, stats in theme_stats.items():
        count = stats["c"]
        question_theme_summary.append({
            "grouping_key": key,
            "domain": stats["d"],
            "num_responses": count,
            "num_models": len(stats["models"]),
            "pct_complete_overall": (stats["p"] / count * 100) if count > 0 else 0,
            "pct_evasive": (stats["e"] / count * 100) if count > 0 else 0,
            "pct_denial": (stats["de"] / count * 100) if count > 0 else 0,
            "pct_error": (stats["er"] / count * 100) if count > 0 else 0
        })
     # Default sort by compliance ascending, then grouping key
    question_theme_summary.sort(key=lambda x: (x["pct_complete_overall"], x["grouping_key"]))
    print(f"Calculated summary for {len(question_theme_summary)} question themes.")

    return {
        "model_summary": model_summary,
        "question_theme_summary": question_theme_summary
    }


def save_data_chunk(filename, records_chunk):
    # Only include fields needed for the detail view in the chunks
    chunk_to_save = []
    needed_keys = ['id', 'anchor_id', 'model', 'timestamp', 'compliance', 'response_text',
                   'judge_analysis', 'judge_model', 'error_message', 'is_partial_response',
                   'original_question_id', 'question_text', 'domain', 'sub_topic_key',
                   'variation', 'grouping_key']
    for record in records_chunk:
        chunk_to_save.append({k: record.get(k) for k in needed_keys})

    output_data = {"records": chunk_to_save}
    print(f"  Saving {len(records_chunk)} records (detail fields only) to {filename}...")
    try:
        with gzip.open(filename, 'wt', encoding='utf-8', compresslevel=9) as f:
            json.dump(output_data, f, ensure_ascii=False, separators=(',', ':'))
        print(f"  Successfully saved {filename} ({os.path.getsize(filename) / 1024 / 1024:.2f} MB).")
        return True
    except Exception as e:
        print(f"Error saving data chunk to {filename}: {e}")
        return False

def save_metadata(filename, data_filenames, compliance_order, stats, model_metadata, summaries):
    metadata = {
        "complianceOrder": compliance_order,
        "data_files": data_filenames,
        "stats": stats,
        "model_metadata": model_metadata,
        "model_summary": summaries["model_summary"], # Add pre-calculated summaries
        "question_theme_summary": summaries["question_theme_summary"]
    }
    print(f"\nSaving metadata to {filename}...")
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"Successfully saved {filename}.")
    except Exception as e:
        print(f"Error saving metadata: {e}")
        sys.exit(1)

def main():
    print("Starting preprocessing...")
    model_meta_dict = load_model_metadata(MODEL_METADATA_FILE)
    all_data = preprocess_us_hard_data(ANALYSIS_DIR)

    if not all_data:
        print("No data processed. Exiting.")
        sys.exit(0)

    total_records = len(all_data)
    print(f"\nTotal records processed: {total_records}")

    # Calculate summaries before splitting/saving chunks
    summaries = calculate_summaries(all_data, model_meta_dict)

    # Calculate overall stats
    num_models = len(summaries["model_summary"])
    num_themes = len(summaries["question_theme_summary"])
    num_judgments = total_records

    stats_summary = { "models": num_models, "themes": num_themes, "judgments": num_judgments }
    print("Calculated Stats:", stats_summary)

    num_files = math.ceil(total_records / MAX_RECORDS_PER_FILE) if total_records > 0 else 0
    print(f"Splitting data into {num_files} file(s) (max {MAX_RECORDS_PER_FILE} records per file).")

    generated_data_files = []
    base_name = OUTPUT_DATA_BASE_FILENAME
    ext = ".json.gz"

    for i in range(num_files):
        start_index = i * MAX_RECORDS_PER_FILE
        end_index = start_index + MAX_RECORDS_PER_FILE
        # Pass the full record chunk to save_data_chunk
        records_chunk = all_data[start_index:end_index]
        output_filename = f"{base_name}_{i+1}{ext}"

        if save_data_chunk(output_filename, records_chunk):
             generated_data_files.append(output_filename)
        else:
             print(f"ERROR: Failed to save chunk {i+1}. Aborting metadata generation.")
             sys.exit(1)

    # Save metadata file including stats, model metadata, and summaries
    save_metadata(OUTPUT_METADATA_FILENAME, generated_data_files, COMPLIANCE_ORDER, stats_summary, model_meta_dict, summaries)

    print("\nPreprocessing and saving complete.")

if __name__ == "__main__": main()
