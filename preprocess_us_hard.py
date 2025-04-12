import json
import os
from glob import glob
import re
import sys

# --- Configuration ---
ANALYSIS_DIR = "analysis"
OUTPUT_JSON_FILE = "us_hard_data.json"
COMPLIANCE_ORDER = ['COMPLETE', 'EVASIVE', 'DENIAL', 'ERROR', 'UNKNOWN']
ID_REGEX = re.compile(r"^(.*?)(\d+)$")
# ** NEW: Standard Error Message **
ERROR_MSG_CENSORSHIP = "ERROR: This typically indicates moderation or censorship systems that have prevented the model from replying, or cancelled a response."

def generate_safe_id(text):
    """Generates a URL-safe ID from text."""
    safe_text = re.sub(r'[^\w\s-]', '', text.lower())
    safe_text = re.sub(r'\s+', '-', safe_text)
    safe_text = safe_text.strip('-')
    return safe_text if safe_text else "id"

def preprocess_us_hard_data(analysis_dir):
    """Loads, preprocesses, and returns us_hard data records as a list of dicts."""
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
                        model = rec.get('model', 'unknown_model')
                        timestamp = rec.get('timestamp', '')
                        compliance = rec.get('compliance', 'UNKNOWN').upper()
                        domain = rec.get('domain', 'Unknown Domain')
                        question_text = rec.get('question', '')
                        judge_analysis = rec.get('judge_analysis', '') # Get original judge analysis
                        judge_model = rec.get('judge_model', '')

                        # --- Parse us_hard specific fields ---
                        sub_topic_key = original_question_id; variation = '0'
                        match = ID_REGEX.match(original_question_id)
                        if match: sub_topic_key, variation = match.groups()
                        else:
                            if original_question_id != f'unknown_id_{line_num+1}':
                                print(f"    Warn: QID format '{original_question_id}' mismatch ln {line_num+1} in {fname}.")
                                skipped_id_format += 1
                        grouping_key = sub_topic_key

                        # --- Response & Error Processing ---
                        response_content = ""; error_message = None; is_partial_response = False
                        response_obj = rec.get('response')

                        # ** REVISED ERROR HANDLING **
                        if compliance == 'ERROR':
                            is_partial_response = True
                            # Use standard message if judge didn't provide one
                            if not judge_analysis:
                                judge_analysis = ERROR_MSG_CENSORSHIP
                            # Try to get partial content and specific API error msg
                            if isinstance(response_obj, dict) and response_obj.get('choices'):
                                choice = response_obj['choices'][0]
                                if isinstance(choice.get('message'), dict):
                                    response_content = choice['message'].get('content', '') # Get partial if exists
                                if isinstance(choice.get('error'), dict):
                                    error_message = choice['error'].get('message', 'Unknown API error structure')
                                else:
                                     # If compliance is ERROR but no 'error' field, still note it
                                     error_message = "(Compliance judged as ERROR, specific API error details missing)"
                            else:
                                # If compliance is ERROR but no response object, note that
                                error_message = "(Compliance judged as ERROR, response object missing/malformed)"
                                response_content = "(No response content due to error)"

                        # Process non-ERROR responses normally
                        elif isinstance(response_obj, dict) and response_obj.get('choices'):
                            choice = response_obj['choices'][0]
                            if isinstance(choice.get('message'), dict):
                                response_content = choice['message'].get('content', '')
                            # If an error field exists but compliance wasn't ERROR, flag it.
                            if isinstance(choice.get('error'), dict):
                                print(f"    Warn: Found API error in {fname}, ln {line_num+1} but compliance='{compliance}'. Overriding.")
                                compliance = 'ERROR'
                                error_message = choice['error'].get('message', 'Unknown API error structure')
                                is_partial_response = True
                                if not judge_analysis: judge_analysis = ERROR_MSG_CENSORSHIP

                        # Final compliance check
                        if compliance not in COMPLIANCE_ORDER:
                            print(f"    Warn: Final invalid compliance '{compliance}' ln {line_num+1}. Setting UNKNOWN.")
                            compliance = 'UNKNOWN'

                        safe_model_id_part = generate_safe_id(model)
                        record_id = f"{model}-{original_question_id}-{timestamp}"
                        # Anchor ID needs to be unique per model *within* the question theme page
                        anchor_id = f"response-{safe_model_id_part}" # Changed: Was variation, now just model

                        all_records.append({
                            'id': record_id, 'anchor_id': anchor_id, 'model': model, 'timestamp': timestamp,
                            'compliance': compliance, 'response_text': response_content, 'judge_analysis': judge_analysis,
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

def main():
    """Main function to preprocess us_hard data and save to JSON."""
    print("Starting preprocessing for us_hard data...")
    all_data = preprocess_us_hard_data(ANALYSIS_DIR)
    output_data = {"complianceOrder": COMPLIANCE_ORDER, "records": all_data}
    print(f"\nSaving {len(all_data)} records to {OUTPUT_JSON_FILE}...")
    try:
        with open(OUTPUT_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=None)
        print("Successfully saved data.")
    except Exception as e: print(f"Error saving data: {e}"); sys.exit(1)

if __name__ == "__main__": main()
