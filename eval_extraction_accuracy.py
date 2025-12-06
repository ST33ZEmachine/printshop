"""
Extraction Accuracy Evaluation

This script validates the extraction pipeline by comparing extracted fields
against the original source data (pre-extraction JSON).

Checks:
1. Purchaser: Does it match the first segment before "|" in the title?
2. Order Summary: Does it match the second segment between first and second "|"?
3. Buyer Email: Does the extracted email actually appear in the original description?
4. Buyer Name: Does the extracted name actually appear in the original description?

Usage:
    python eval_extraction_accuracy.py [--sample-size N]
"""

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_json(filepath: str) -> Dict[str, Any]:
    """Load a JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_title_segments(title: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extract expected purchaser and order_summary from title.
    Title format: "Purchaser | Order Summary | Additional Info"
    """
    if not title or "|" not in title:
        return None, None
    
    parts = [p.strip() for p in title.split("|")]
    purchaser = parts[0] if len(parts) > 0 and parts[0] else None
    order_summary = parts[1] if len(parts) > 1 and parts[1] else None
    
    return purchaser, order_summary


def check_text_in_description(text: str, description: str) -> bool:
    """
    Check if text appears in description (case-insensitive).
    """
    if not text or not description:
        return False
    return text.lower() in description.lower()


def check_email_in_description(email: str, description: str) -> bool:
    """
    Check if email appears in description.
    Also checks for common variations (spaces, different formatting).
    """
    if not email or not description:
        return False
    
    email_lower = email.lower()
    desc_lower = description.lower()
    
    # Direct match
    if email_lower in desc_lower:
        return True
    
    # Check without spaces (some emails might be formatted differently)
    email_no_space = email_lower.replace(" ", "")
    if email_no_space in desc_lower.replace(" ", ""):
        return True
    
    # Extract all emails from description and check
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    found_emails = re.findall(email_pattern, description)
    return email_lower in [e.lower() for e in found_emails]


def evaluate_card(original: Dict, enriched: Dict) -> Dict[str, Any]:
    """
    Evaluate extraction accuracy for a single card.
    
    Returns dict with evaluation results.
    """
    results = {
        "card_id": original.get("id"),
        "card_name": original.get("name", "")[:80],
    }
    
    original_title = original.get("name", "")
    original_desc = original.get("desc", "")
    
    # 1. Check purchaser extraction
    expected_purchaser, expected_order_summary = extract_title_segments(original_title)
    extracted_purchaser = enriched.get("purchaser")
    
    if expected_purchaser is None and extracted_purchaser is None:
        results["purchaser_correct"] = True
        results["purchaser_note"] = "Both null (no | in title)"
    elif expected_purchaser == extracted_purchaser:
        results["purchaser_correct"] = True
        results["purchaser_note"] = "Exact match"
    else:
        results["purchaser_correct"] = False
        results["purchaser_note"] = f"Expected '{expected_purchaser}', got '{extracted_purchaser}'"
    
    # 2. Check order_summary extraction
    extracted_order_summary = enriched.get("order_summary")
    
    if expected_order_summary is None and extracted_order_summary is None:
        results["order_summary_correct"] = True
        results["order_summary_note"] = "Both null (no second | segment)"
    elif expected_order_summary == extracted_order_summary:
        results["order_summary_correct"] = True
        results["order_summary_note"] = "Exact match"
    else:
        results["order_summary_correct"] = False
        results["order_summary_note"] = f"Expected '{expected_order_summary}', got '{extracted_order_summary}'"
    
    # 3. Check buyer email extraction
    extracted_email = enriched.get("primary_buyer_email")
    
    if extracted_email is None:
        # No email extracted - check if there's actually an email in the description
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        found_emails = re.findall(email_pattern, original_desc)
        if found_emails:
            results["email_correct"] = False
            results["email_note"] = f"Missed email(s): {found_emails[:3]}"
            results["email_false_negative"] = True
        else:
            results["email_correct"] = True
            results["email_note"] = "No email in description, none extracted"
            results["email_false_negative"] = False
    else:
        # Email was extracted - verify it exists in original
        if check_email_in_description(extracted_email, original_desc):
            results["email_correct"] = True
            results["email_note"] = f"Found '{extracted_email}' in description"
            results["email_false_negative"] = False
        elif check_email_in_description(extracted_email, original_title):
            results["email_correct"] = True
            results["email_note"] = f"Found '{extracted_email}' in title"
            results["email_false_negative"] = False
        else:
            results["email_correct"] = False
            results["email_note"] = f"'{extracted_email}' NOT found in original"
            results["email_false_negative"] = False
            results["email_false_positive"] = True
    
    # 4. Check buyer name extraction
    extracted_name = enriched.get("primary_buyer_name")
    
    if extracted_name is None:
        results["name_correct"] = True  # Can't easily verify false negatives for names
        results["name_note"] = "No name extracted"
    else:
        # Name was extracted - check if it appears in description or title
        if check_text_in_description(extracted_name, original_desc):
            results["name_correct"] = True
            results["name_note"] = f"Found '{extracted_name}' in description"
        elif check_text_in_description(extracted_name, original_title):
            results["name_correct"] = True
            results["name_note"] = f"Found '{extracted_name}' in title"
        else:
            # Check if name parts appear (first/last name separately)
            name_parts = extracted_name.split()
            if len(name_parts) > 1:
                parts_found = sum(1 for p in name_parts if check_text_in_description(p, original_desc + " " + original_title))
                if parts_found >= len(name_parts) - 1:  # Allow one part missing
                    results["name_correct"] = True
                    results["name_note"] = f"Name parts found: {extracted_name}"
                else:
                    results["name_correct"] = False
                    results["name_note"] = f"'{extracted_name}' NOT found in original"
            else:
                results["name_correct"] = False
                results["name_note"] = f"'{extracted_name}' NOT found in original"
    
    return results


def run_evaluation(
    original_file: str,
    enriched_file: str,
    sample_size: int = 100
) -> Dict[str, Any]:
    """
    Run full extraction accuracy evaluation.
    """
    print(f"\nLoading original file: {original_file}")
    original_data = load_json(original_file)
    original_cards = original_data.get("cards", [])
    print(f"  Loaded {len(original_cards)} original cards")
    
    print(f"\nLoading enriched file: {enriched_file}")
    enriched_data = load_json(enriched_file)
    enriched_cards = enriched_data.get("cards", [])
    print(f"  Loaded {len(enriched_cards)} enriched cards")
    
    # Create lookup by card ID
    enriched_by_id = {c.get("id"): c for c in enriched_cards}
    
    # Sample cards
    if sample_size >= len(original_cards):
        sample = original_cards
    else:
        sample = random.sample(original_cards, sample_size)
    
    print(f"\nEvaluating {len(sample)} sampled cards...")
    
    results = []
    for original in sample:
        card_id = original.get("id")
        enriched = enriched_by_id.get(card_id)
        
        if enriched is None:
            print(f"  Warning: Card {card_id} not found in enriched data")
            continue
        
        eval_result = evaluate_card(original, enriched)
        results.append(eval_result)
    
    # Calculate summary statistics
    total = len(results)
    
    purchaser_correct = sum(1 for r in results if r.get("purchaser_correct"))
    order_summary_correct = sum(1 for r in results if r.get("order_summary_correct"))
    email_correct = sum(1 for r in results if r.get("email_correct"))
    name_correct = sum(1 for r in results if r.get("name_correct"))
    
    email_false_negatives = sum(1 for r in results if r.get("email_false_negative"))
    email_false_positives = sum(1 for r in results if r.get("email_false_positive"))
    
    summary = {
        "total_evaluated": total,
        "purchaser_accuracy": purchaser_correct / total * 100 if total > 0 else 0,
        "order_summary_accuracy": order_summary_correct / total * 100 if total > 0 else 0,
        "email_accuracy": email_correct / total * 100 if total > 0 else 0,
        "name_accuracy": name_correct / total * 100 if total > 0 else 0,
        "email_false_negatives": email_false_negatives,
        "email_false_positives": email_false_positives,
    }
    
    return {
        "summary": summary,
        "detailed_results": results,
    }


def print_results(evaluation: Dict[str, Any]):
    """Print evaluation results in a readable format."""
    summary = evaluation["summary"]
    results = evaluation["detailed_results"]
    
    print("\n" + "="*70)
    print("EXTRACTION ACCURACY EVALUATION RESULTS")
    print("="*70)
    
    print(f"\nTotal Cards Evaluated: {summary['total_evaluated']}")
    
    print("\n" + "-"*70)
    print("ACCURACY BY FIELD:")
    print("-"*70)
    
    print(f"\n1. PURCHASER (title parsing):")
    print(f"   Accuracy: {summary['purchaser_accuracy']:.1f}%")
    
    print(f"\n2. ORDER SUMMARY (title parsing):")
    print(f"   Accuracy: {summary['order_summary_accuracy']:.1f}%")
    
    print(f"\n3. BUYER EMAIL (LLM extraction):")
    print(f"   Accuracy: {summary['email_accuracy']:.1f}%")
    print(f"   False Negatives (missed emails): {summary['email_false_negatives']}")
    print(f"   False Positives (hallucinated): {summary['email_false_positives']}")
    
    print(f"\n4. BUYER NAME (LLM extraction):")
    print(f"   Accuracy: {summary['name_accuracy']:.1f}%")
    
    # Show some examples of errors
    errors = [r for r in results if not r.get("purchaser_correct") or 
              not r.get("order_summary_correct") or 
              not r.get("email_correct") or
              not r.get("name_correct")]
    
    if errors:
        print("\n" + "-"*70)
        print("SAMPLE ERRORS (first 10):")
        print("-"*70)
        
        for i, err in enumerate(errors[:10]):
            print(f"\n[{i+1}] Card: {err['card_name']}")
            if not err.get("purchaser_correct"):
                print(f"    ❌ Purchaser: {err.get('purchaser_note')}")
            if not err.get("order_summary_correct"):
                print(f"    ❌ Order Summary: {err.get('order_summary_note')}")
            if not err.get("email_correct"):
                print(f"    ❌ Email: {err.get('email_note')}")
            if not err.get("name_correct"):
                print(f"    ❌ Name: {err.get('name_note')}")
    
    print("\n" + "="*70)
    print("OVERALL ASSESSMENT")
    print("="*70)
    
    avg_accuracy = (summary['purchaser_accuracy'] + summary['order_summary_accuracy'] + 
                   summary['email_accuracy'] + summary['name_accuracy']) / 4
    
    print(f"\nAverage Accuracy: {avg_accuracy:.1f}%")
    
    if avg_accuracy >= 95:
        print("Assessment: ✅ EXCELLENT - Extraction pipeline is highly accurate")
    elif avg_accuracy >= 85:
        print("Assessment: ✅ GOOD - Extraction pipeline is working well")
    elif avg_accuracy >= 70:
        print("Assessment: ⚠️ ACCEPTABLE - Some extraction issues to investigate")
    else:
        print("Assessment: ❌ NEEDS IMPROVEMENT - Significant extraction errors")
    
    print("="*70)


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate extraction accuracy against original source data"
    )
    parser.add_argument(
        "--original",
        type=str,
        default="extractionPipeline/LyB2G53h.json",
        help="Path to original (pre-extraction) JSON file"
    )
    parser.add_argument(
        "--enriched",
        type=str,
        default="extractionPipeline/bourquin_05122025_snapshot.json",
        help="Path to enriched (post-extraction) JSON file"
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=200,
        help="Number of cards to sample for evaluation (default: 200)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility"
    )
    
    args = parser.parse_args()
    
    # Set random seed for reproducibility
    random.seed(args.seed)
    
    # Run evaluation
    evaluation = run_evaluation(
        args.original,
        args.enriched,
        args.sample_size
    )
    
    # Print results
    print_results(evaluation)
    
    return evaluation


if __name__ == "__main__":
    main()

