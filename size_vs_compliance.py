#!/usr/bin/env python3
"""
Script to analyze within-model-family correlations and combine signals statistically.
"""

import json
import re
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict
from scipy.stats import pearsonr, combine_pvalues
import pandas as pd

# Configuration
MODEL_METADATA_FILE = "model_metadata.json"
METADATA_FILE = "metadata.json"
SIZE_REGEX = re.compile(r'\b([0-9]+)b\b', re.IGNORECASE)

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

def extract_model_size(model_identifier):
    """Extract model size in billions from model identifier"""
    match = SIZE_REGEX.search(model_identifier)
    if match:
        return int(match.group(1))
    return None

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

def analyze_model_family_correlations():
    """Analyze within-model-family correlations and combine signals"""
    # Load data
    model_metadata = load_model_metadata(MODEL_METADATA_FILE)
    compliance_data = load_compliance_data(METADATA_FILE)
    
    if not model_metadata or not compliance_data:
        print("Failed to load required data files")
        return
    
    # Extract size and compliance data, grouped by model family
    family_data = defaultdict(list)
    
    for model_stats in compliance_data:
        model_id = model_stats["model"]
        compliance_rate = model_stats["pct_complete_overall"]
        
        # Extract size from model identifier
        size = extract_model_size(model_id)
        
        if size is not None:
            # Get model family from metadata
            metadata = model_metadata.get(model_id, {})
            family = metadata.get("model_family", "unknown")
            creator = metadata.get("creator", "unknown")
            
            family_data[family].append({
                "model_id": model_id,
                "size": size,
                "compliance_rate": compliance_rate,
                "creator": creator,
                "num_responses": model_stats["num_responses"]
            })
    
    if not family_data:
        print("No models found with size information")
        return
    
    print("STEP 1: Within-Model-Family Analysis")
    print("=" * 80)
    print(f"{'Model Family':<25} {'Models':<7} {'Creator':<12} {'Sizes':<15} {'r':<8} {'p-val':<8}")
    print("-" * 80)
    
    family_correlations = []
    valid_correlations = []  # For meta-analysis
    
    for family, models in family_data.items():
        creator = models[0]["creator"]  # All should be same creator
        sizes = [m["size"] for m in models]
        rates = [m["compliance_rate"] for m in models]
        size_range = f"{min(sizes)}-{max(sizes)}B" if len(set(sizes)) > 1 else f"{sizes[0]}B"
        
        if len(models) >= 2 and len(set(sizes)) > 1:  # Need at least 2 models with different sizes
            r, p_value = pearsonr(sizes, rates)
            
            family_correlations.append({
                "family": family,
                "creator": creator,
                "correlation": r,
                "p_value": p_value,
                "num_models": len(models),
                "models": models,
                "size_range": size_range
            })
            
            # Store for meta-analysis (only if we have a valid correlation)
            if not np.isnan(r):
                valid_correlations.append({
                    "family": family,
                    "r": r,
                    "p": p_value,
                    "n": len(models)
                })
            
            print(f"{family:<25} {len(models):<7} {creator:<12} {size_range:<15} {r:<8.3f} {p_value:<8.3f}")
        else:
            reason = "Same size" if len(set(sizes)) == 1 else "Too few"
            print(f"{family:<25} {len(models):<7} {creator:<12} {size_range:<15} {'N/A':<8} {reason}")
    
    if not valid_correlations:
        print("\nNo valid correlations found within model families.")
        return
    
    print(f"\n\nSTEP 2: Meta-Analysis Combining Signals")
    print("=" * 50)
    
    # Method 1: Simple average of correlation coefficients (Fisher's z-transform)
    print("\nMethod 1: Fisher's Z-Transform Meta-Analysis")
    z_scores = []
    weights = []
    
    for corr in valid_correlations:
        r = corr["r"]
        n = corr["n"]
        
        # Fisher z-transform: z = 0.5 * ln((1+r)/(1-r))
        if abs(r) < 0.999:  # Avoid division by zero
            z = 0.5 * np.log((1 + r) / (1 - r))
            weight = n - 3  # Sample size - 3 for Fisher transform
            
            z_scores.append(z)
            weights.append(weight)
    
    if z_scores:
        # Weighted average of z-scores
        weighted_z = np.average(z_scores, weights=weights)
        
        # Transform back to correlation
        combined_r = (np.exp(2 * weighted_z) - 1) / (np.exp(2 * weighted_z) + 1)
        
        # Standard error and confidence interval
        se_z = 1 / np.sqrt(sum(weights))
        z_lower = weighted_z - 1.96 * se_z
        z_upper = weighted_z + 1.96 * se_z
        
        r_lower = (np.exp(2 * z_lower) - 1) / (np.exp(2 * z_lower) + 1)
        r_upper = (np.exp(2 * z_upper) - 1) / (np.exp(2 * z_upper) + 1)
        
        print(f"Combined correlation: r = {combined_r:.3f}")
        print(f"95% CI: [{r_lower:.3f}, {r_upper:.3f}]")
        
        # Test if significantly different from zero
        z_stat = weighted_z / se_z
        p_combined = 2 * (1 - np.abs(z_stat))  # Two-tailed
        print(f"Test vs zero: z = {z_stat:.3f}, p = {p_combined:.3f}")
    
    # Method 2: Combine p-values using Fisher's method
    print(f"\nMethod 2: Fisher's Method for Combining P-values")
    p_values = [corr["p"] for corr in valid_correlations]
    
    if len(p_values) >= 2:
        # Fisher's method
        chi2_stat, fisher_p = combine_pvalues(p_values, method='fisher')
        print(f"Combined p-value (Fisher): {fisher_p:.6f}")
        
        # Stouffer's method (assumes equal weights)
        try:
            stouffer_stat, stouffer_p = combine_pvalues(p_values, method='stouffer')
            print(f"Combined p-value (Stouffer): {stouffer_p:.6f}")
        except:
            print("Stouffer method failed")
    
    # Method 3: Simple vote counting
    print(f"\nMethod 3: Direction Analysis")
    negative_corrs = [c for c in valid_correlations if c["r"] < 0]
    positive_corrs = [c for c in valid_correlations if c["r"] > 0]
    
    print(f"Model families supporting hypothesis (smaller = less permissive): {len(negative_corrs)}")
    print(f"Model families contradicting hypothesis: {len(positive_corrs)}")
    
    if negative_corrs:
        print("Supporting families:")
        for c in negative_corrs:
            print(f"  - {c['family']}: r = {c['r']:.3f}, p = {c['p']:.3f}")
    
    if positive_corrs:
        print("Contradicting families:")
        for c in positive_corrs:
            print(f"  - {c['family']}: r = {c['r']:.3f}, p = {c['p']:.3f}")
    
    # Create visualization
    if len(valid_correlations) >= 2:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        
        # Left plot: Individual family correlations
        families = [c["family"] for c in valid_correlations]
        correlations = [c["r"] for c in valid_correlations]
        colors = ['red' if r < 0 else 'blue' for r in correlations]
        
        bars = ax1.bar(range(len(families)), correlations, color=colors, alpha=0.7)
        ax1.set_xticks(range(len(families)))
        ax1.set_xticklabels(families, rotation=45, ha='right')
        ax1.set_ylabel('Correlation Coefficient')
        ax1.set_title('Size-Compliance Correlation by Model Family')
        ax1.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        ax1.grid(True, alpha=0.3)
        
        # Add significance markers
        for i, (bar, corr) in enumerate(zip(bars, valid_correlations)):
            if corr["p"] < 0.05:
                ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                        '*', ha='center', va='bottom', fontweight='bold')
        
        # Right plot: Forest plot style
        y_pos = range(len(valid_correlations))
        ax2.errorbar([c["r"] for c in valid_correlations], y_pos,
                    xerr=[[c["r"] - max(c["r"] - 0.5, -1) for c in valid_correlations],
                          [min(c["r"] + 0.5, 1) - c["r"] for c in valid_correlations]],
                    fmt='o', capsize=5)
        
        ax2.set_yticks(y_pos)
        ax2.set_yticklabels([c["family"] for c in valid_correlations])
        ax2.set_xlabel('Correlation Coefficient')
        ax2.set_title('Forest Plot: Family Correlations')
        ax2.axvline(x=0, color='black', linestyle='-', alpha=0.3)
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.show()
        plt.savefig("family_correlations_meta_analysis.png", dpi=300, bbox_inches='tight')
    
    print(f"\n\nCONCLUSION:")
    if len(valid_correlations) < 2:
        print("Insufficient data for meta-analysis.")
    else:
        print(f"Analyzed {len(valid_correlations)} model families with size variation.")
        if 'combined_r' in locals():
            if combined_r < -0.1 and p_combined < 0.05:
                print("✓ SUPPORTS hypothesis: Meta-analysis shows smaller models are less permissive")
            elif combined_r > 0.1 and p_combined < 0.05:
                print("✗ CONTRADICTS hypothesis: Meta-analysis shows larger models are less permissive")
            else:
                print("? INCONCLUSIVE: No significant overall trend detected")

if __name__ == "__main__":
    analyze_model_family_correlations()
