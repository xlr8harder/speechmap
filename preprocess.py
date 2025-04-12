import json
import os
from glob import glob
import re
import sys
import gzip
import math

# --- Configuration ---
ANALYSIS_DIR = "analysis"
OUTPUT_DATA_BASE_FILENAME = "speechdata" # Base name for data files (data_1, data_2, ...)
OUTPUT_METADATA_FILENAME = "metadata.json" # Metadata file name
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

def preprocess_us_hard_data(analysis_dir):
    all_records = []
    file_paths = glob(os.path.join(analysis_dir, "compliance_us_hard_*.jsonl"))
    print(f"\nFound {len(file_paths)} us_hard analysis files in {analysis_dir}")
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
                                print(f"    Warn: QID format '{original_question_id}' mismatch ln {line_num+1}. Using defaults.")
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
                                print(f"    Warn: API error ln {line_num+1} but compliance='{compliance}'. Forcing ERROR.")
                                compliance = 'ERROR'; is_partial_response = True;
                                specific_api_error = choice['error'].get('message', 'Unknown API error structure')
                                error_message = ERROR_MSG_CENSORSHIP
                                if specific_api_error and specific_api_error != 'Unknown API error structure':
                                      error_message += f" [API Msg: {specific_api_error}]"
                                if not judge_analysis: judge_analysis = JUDGE_ANALYSIS_FOR_ERROR

                        if compliance not in COMPLIANCE_ORDER: compliance = 'UNKNOWN'

                        safe_model_id_part = generate_safe_id(model)
                        record_id = f"{model}-{original_question_id}-{timestamp}"
                        anchor_id = f"response-{safe_model_id_part}"

                        all_records.append({
                            'id': record_id, 'anchor_id': anchor_id, 'model': model, 'timestamp': timestamp,
                            'compliance': compliance, 'response_text': response_content, 'judge_analysis': judge_analysis,
                            'judge_model': judge_model, 'error_message': error_message, 'is_partial_response': is_partial_response,
                            'original_question_id': original_question_id, 'question_text': question_text,
                            'domain': domain, 'sub_topic_key': sub_topic_key, 'variation': variation,
                            'grouping_key': grouping_key })
                        processed_count += 1
                    except Exception as e: print(f"    ERR Proc Line {line_num+1} in {fname}: {e} - Rec: {rec}"); error_count += 1
        except Exception as e: print(f"  ERR Reading File {fname}: {e}"); error_count += 1

    print(f"\nPreprocessing finished. Processed: {processed_count}, Skipped Format: {skipped_id_format}, Errors: {error_count}")
    return all_records

# Updated function: only saves records chunk
def save_data_chunk(filename, records_chunk):
    output_data = {"records": records_chunk} # Only records here
    print(f"  Saving {len(records_chunk)} records to {filename}...")
    try:
        with gzip.open(filename, 'wt', encoding='utf-8', compresslevel=9) as f:
            json.dump(output_data, f, ensure_ascii=False, separators=(',', ':'))
        print(f"  Successfully saved {filename} ({os.path.getsize(filename) / 1024 / 1024:.2f} MB).")
        return True # Indicate success
    except Exception as e:
        print(f"Error saving data chunk to {filename}: {e}")
        return False # Indicate failure

def save_metadata(filename, data_filenames, compliance_order):
    metadata = {
        "complianceOrder": compliance_order,
        "data_files": data_filenames
    }
    print(f"\nSaving metadata to {filename}...")
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2) # Use indent for readability
        print(f"Successfully saved {filename}.")
    except Exception as e:
        print(f"Error saving metadata: {e}")
        sys.exit(1) # Exit if metadata fails, crucial file

def main():
    print("Starting preprocessing...")
    all_data = preprocess_us_hard_data(ANALYSIS_DIR)

    if not all_data:
        print("No data processed. Exiting.")
        sys.exit(0)

    total_records = len(all_data)
    print(f"\nTotal records processed: {total_records}")

    num_files = math.ceil(total_records / MAX_RECORDS_PER_FILE)
    print(f"Splitting data into {num_files} file(s) (max {MAX_RECORDS_PER_FILE} records per file).")

    generated_data_files = []
    base_name = OUTPUT_DATA_BASE_FILENAME # e.g., "data"
    ext = ".json.gz"

    for i in range(num_files):
        start_index = i * MAX_RECORDS_PER_FILE
        end_index = start_index + MAX_RECORDS_PER_FILE
        records_chunk = all_data[start_index:end_index]
        output_filename = f"{base_name}_{i+1}{ext}" # e.g., data_1.json.gz

        if save_data_chunk(output_filename, records_chunk):
            generated_data_files.append(output_filename) # Add to list only if saved successfully
        else:
             print(f"ERROR: Failed to save chunk {i+1}. Aborting metadata generation.")
             sys.exit(1) # Don't generate metadata if a chunk failed

    # Save metadata file listing the generated data files
    save_metadata(OUTPUT_METADATA_FILENAME, generated_data_files, COMPLIANCE_ORDER)

    print("\nPreprocessing and saving complete.")

if __name__ == "__main__": main()
