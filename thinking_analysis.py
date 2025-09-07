#!/usr/bin/env python3
"""
Script to compare compliance rates between thinking and non-thinking model pairs.
"""

import json
import re
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
from scipy.stats import ttest_rel, wilcoxon

# Configuration
MODEL_METADATA_FILE = "model_metadata.json"
METADATA_FILE = "metadata.json"

def load_model_metadata(filepath):
    """Load model metadata from JSONL file"""
    metadata = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line.strip())
                    identifier = data.get("model_identifier")
                    if identifier:
                        metadata[identifier] = data
    except FileNotFoundError:
        print(f"Error: {filepath} not found")
        return {}
    except Exception as e:
        print(f"Error loading model metadata: {e}")
        return {}
    
    return metadata

def load_compliance_data(filepath):
    """Load compliance summary data"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("model_summary", [])
    except FileNotFoundError:
        print(f"Error: {filepath} not found")
        return []
    except Exception as e:
        print(f"Error loading compliance data: {e}")
        return []

def find_base_model_name(model_id):
    """Extract base model name by removing -thinking suffix"""
    if model_id.endswith('-thinking'):
        return model_id[:-9]  # Remove '-thinking'
    return model_id

def analyze_thinking_vs_nonthinking():
    """Compare compliance rates between thinking and non-thinking model pairs"""
    # Load data
    model_metadata = load_model_metadata(MODEL_METADATA_FILE)
    compliance_data = load_compliance_data(METADATA_FILE)
    
    if not model_metadata or not compliance_data:
        print("Failed to load required data files")
        return
    
    # Create lookup for compliance data by model ID
    compliance_lookup = {model["model"]: model for model in compliance_data}
    
    # Find thinking/non-thinking pairs
    thinking_models = []
    nonthinking_models = []
    
    for model_id, metadata in model_metadata.items():
        if metadata.get("reasoning_model", False):
            thinking_models.append(model_id)
        else:
            nonthinking_models.append(model_id)
    
    print(f"Found {len(thinking_models)} reasoning models and {len(nonthinking_models)} non-reasoning models")
    
    # Find pairs
    model_pairs = []
    
    for thinking_model in thinking_models:
        base_name = find_base_model_name(thinking_model)
        
        # Look for matching non-thinking model
        matching_nonthinking = None
        for nonthinking_model in nonthinking_models:
            if nonthinking_model == base_name:
                matching_nonthinking = nonthinking_model
                break
        
        if matching_nonthinking and thinking_model in compliance_lookup and matching_nonthinking in compliance_lookup:
            thinking_compliance = compliance_lookup[thinking_model]
            nonthinking_compliance = compliance_lookup[matching_nonthinking]
            
            # Get model family for grouping
            thinking_metadata = model_metadata[thinking_model]
            nonthinking_metadata = model_metadata[matching_nonthinking]
            
            model_pairs.append({
                "base_name": base_name,
                "thinking_model": thinking_model,
                "nonthinking_model": matching_nonthinking,
                "thinking_compliance": thinking_compliance["pct_complete_overall"],
                "nonthinking_compliance": nonthinking_compliance["pct_complete_overall"],
                "thinking_responses": thinking_compliance["num_responses"],
                "nonthinking_responses": nonthinking_compliance["num_responses"],
                "family": thinking_metadata.get("model_family", "unknown"),
                "creator": thinking_metadata.get("creator", "unknown"),
                "difference": thinking_compliance["pct_complete_overall"] - nonthinking_compliance["pct_complete_overall"]
            })
    
    if not model_pairs:
        print("No matching thinking/non-thinking pairs found!")
        return
    
    print(f"\nFound {len(model_pairs)} thinking/non-thinking pairs:")
    print("=" * 120)
    print(f"{'Base Model':<40} {'Creator':<12} {'Non-Thinking':<8} {'Thinking':<8} {'Difference':<10} {'Effect'}")
    print("-" * 120)
    
    for pair in model_pairs:
        effect = "Thinking MORE compliant" if pair["difference"] > 0 else "Thinking LESS compliant" if pair["difference"] < 0 else "Same"
        print(f"{pair['base_name']:<40} {pair['creator']:<12} {pair['nonthinking_compliance']:<8.1f} {pair['thinking_compliance']:<8.1f} {pair['difference']:<10.1f} {effect}")
    
    # Statistical analysis
    if len(model_pairs) >= 2:
        thinking_rates = [p["thinking_compliance"] for p in model_pairs]
        nonthinking_rates = [p["nonthinking_compliance"] for p in model_pairs]
        differences = [p["difference"] for p in model_pairs]
        
        print(f"\n\nSTATISTICAL ANALYSIS:")
        print("=" * 50)
        
        # Descriptive statistics
        print(f"Mean non-thinking compliance: {np.mean(nonthinking_rates):.2f}%")
        print(f"Mean thinking compliance: {np.mean(thinking_rates):.2f}%")
        print(f"Mean difference (thinking - non-thinking): {np.mean(differences):.2f}%")
        print(f"Std dev of differences: {np.std(differences):.2f}%")
        
        # Paired t-test
        if len(model_pairs) >= 3:
            t_stat, t_p = ttest_rel(thinking_rates, nonthinking_rates)
            print(f"\nPaired t-test:")
            print(f"  t-statistic: {t_stat:.3f}")
            print(f"  p-value: {t_p:.6f}")
            
            # Wilcoxon signed-rank test (non-parametric alternative)
            try:
                w_stat, w_p = wilcoxon(thinking_rates, nonthinking_rates)
                print(f"\nWilcoxon signed-rank test:")
                print(f"  statistic: {w_stat:.3f}")
                print(f"  p-value: {w_p:.6f}")
            except:
                print(f"\nWilcoxon test failed (likely due to tied values)")
        
        # Effect size (Cohen's d for paired samples)
        pooled_std = np.sqrt((np.var(thinking_rates) + np.var(nonthinking_rates)) / 2)
        if pooled_std > 0:
            cohens_d = np.mean(differences) / pooled_std
            print(f"\nEffect size (Cohen's d): {cohens_d:.3f}")
            if abs(cohens_d) < 0.2:
                effect_size_desc = "negligible"
            elif abs(cohens_d) < 0.5:
                effect_size_desc = "small"
            elif abs(cohens_d) < 0.8:
                effect_size_desc = "medium"
            else:
                effect_size_desc = "large"
            print(f"Effect size interpretation: {effect_size_desc}")
    
    # Create visualization
    if len(model_pairs) >= 1:
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 6))
        
        # Plot 1: Paired comparison
        x_pos = range(len(model_pairs))
        thinking_rates = [p["thinking_compliance"] for p in model_pairs]
        nonthinking_rates = [p["nonthinking_compliance"] for p in model_pairs]
        
        ax1.scatter(x_pos, nonthinking_rates, color='blue', alpha=0.7, label='Non-thinking', s=100)
        ax1.scatter(x_pos, thinking_rates, color='red', alpha=0.7, label='Thinking', s=100)
        
        # Connect pairs with lines
        for i, (nt, t) in enumerate(zip(nonthinking_rates, thinking_rates)):
            ax1.plot([i, i], [nt, t], 'k-', alpha=0.3)
        
        # Create shorter, more readable labels
        short_labels = []
        for p in model_pairs:
            # Extract just the model name and key identifiers
            name = p["base_name"].split('/')[-1]
            # Remove common prefixes and long date strings
            name = name.replace('claude-', '').replace('gemini-', '').replace('preview-', '')
            # Keep it short but informative
            if len(name) > 15:
                name = name[:12] + "..."
            short_labels.append(name)
        
        ax1.set_xticks(x_pos)
        ax1.set_xticklabels(short_labels, rotation=45, ha='right')
        ax1.set_ylabel('Compliance Rate (%)')
        ax1.set_title('Thinking vs Non-Thinking Pairs')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Plot 2: Difference plot
        differences = [p["difference"] for p in model_pairs]
        colors = ['red' if d > 0 else 'blue' for d in differences]
        
        bars = ax2.bar(x_pos, differences, color=colors, alpha=0.7)
        ax2.set_xticks(x_pos)
        ax2.set_xticklabels(short_labels, rotation=45, ha='right')
        ax2.set_ylabel('Difference (Thinking - Non-thinking) %')
        ax2.set_title('Compliance Rate Differences')
        ax2.axhline(y=0, color='black', linestyle='-', alpha=0.5)
        ax2.grid(True, alpha=0.3)
        
        # Plot 3: Distribution of differences
        ax3.hist(differences, bins=max(3, len(model_pairs)//2), alpha=0.7, color='green', edgecolor='black')
        ax3.axvline(x=0, color='red', linestyle='--', linewidth=2, label='No difference')
        ax3.axvline(x=np.mean(differences), color='black', linestyle='-', linewidth=2, label=f'Mean: {np.mean(differences):.1f}%')
        ax3.set_xlabel('Difference (Thinking - Non-thinking) %')
        ax3.set_ylabel('Count')
        ax3.set_title('Distribution of Differences')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.show()
        plt.savefig("thinking_vs_nonthinking_compliance.png", dpi=300, bbox_inches='tight')
    
    # Summary
    print(f"\n\nSUMMARY:")
    if len(model_pairs) == 0:
        print("No comparable pairs found.")
    else:
        more_compliant = sum(1 for p in model_pairs if p["difference"] > 0)
        less_compliant = sum(1 for p in model_pairs if p["difference"] < 0)
        same_compliant = sum(1 for p in model_pairs if p["difference"] == 0)
        
        print(f"Out of {len(model_pairs)} pairs:")
        print(f"  - Thinking models MORE compliant: {more_compliant}")
        print(f"  - Thinking models LESS compliant: {less_compliant}")
        print(f"  - Same compliance: {same_compliant}")
        
        if len(model_pairs) >= 3 and 't_p' in locals():
            if t_p < 0.05:
                direction = "more" if np.mean(differences) > 0 else "less"
                print(f"  ✓ SIGNIFICANT: Thinking models are {direction} compliant (p = {t_p:.4f})")
            else:
                print(f"  ? INCONCLUSIVE: No significant difference (p = {t_p:.4f})")

if __name__ == "__main__":
    analyze_thinking_vs_nonthinking()
