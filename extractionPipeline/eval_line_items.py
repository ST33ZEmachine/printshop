#!/usr/bin/env python3
"""
Evaluation script for line item extraction quality.

Compares extracted line items against source descriptions using
regex patterns to verify extraction accuracy.

Usage:
    python eval_line_items.py --csv line_items_test_50.csv --source bourquin_05122025_snapshot.json
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path


def extract_quantities_from_text(text: str) -> list[int]:
    """Extract all quantity patterns like (1), (2), (Qty:4) from text."""
    patterns = [
        r'\((\d+)\)',           # (1), (2)
        r'\(Qty:(\d+)\)',       # (Qty:4)
        r'Qty:(\d+)',           # Qty:4
    ]
    quantities = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            quantities.append(int(match.group(1)))
    return quantities


def normalize_quotes(text: str) -> str:
    """Normalize unicode quotes to ASCII."""
    # Double quotes: U+201C, U+201D, U+201E, U+201F, U+2033, U+301D, U+301E, U+301F
    for code in [0x201C, 0x201D, 0x201E, 0x201F, 0x2033, 0x301D, 0x301E, 0x301F]:
        text = text.replace(chr(code), '"')
    # Single quotes: U+2018, U+2019, U+201A, U+201B, U+2032
    for code in [0x2018, 0x2019, 0x201A, 0x201B, 0x2032]:
        text = text.replace(chr(code), "'")
    return text


def extract_dimensions_from_text(text: str) -> list[tuple]:
    """Extract dimension patterns like 96"x48", 24x36" from text."""
    text = normalize_quotes(text)
    
    patterns = [
        r'(\d+(?:\.\d+)?)["\']?\s*[xX×]\s*(\d+(?:\.\d+)?)["\']?',  # 96"x48" or 96x48
        r'(\d+(?:\.\d+)?)\s*[wW]\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[hH]',  # 96w x 48h
    ]
    dims = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            try:
                w = float(match.group(1))
                h = float(match.group(2))
                dims.append((w, h))
            except:
                pass
    return dims


def extract_prices_from_text(text: str) -> list[float]:
    """Extract price patterns like $489.00, $45, $0.10, $8945.12 from text."""
    text = normalize_quotes(text)
    # Match $X, $X.XX, $X,XXX.XX formats
    pattern = r'\$(\d+(?:,\d{3})*(?:\.\d{1,2})?)'
    prices = []
    for match in re.finditer(pattern, text):
        try:
            price_str = match.group(1).replace(',', '')
            prices.append(float(price_str))
        except:
            pass
    return list(set(prices))  # dedupe


def extract_order_class_from_text(text: str) -> list[str]:
    """Extract order class patterns like Supply, Supply & Install, Install."""
    patterns = [
        r'(Supply\s*(?:&|and)?\s*Install)',
        r'(Install(?:ed)?)',
        r'(Supply)',
    ]
    classes = []
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            match = re.search(pattern, text, re.IGNORECASE)
            classes.append(match.group(1))
    return classes


def evaluate_extraction(csv_path: Path, source_path: Path, limit: int = None):
    """Evaluate extraction quality by comparing to source."""
    
    # Load source cards
    with open(source_path) as f:
        data = json.load(f)
    
    if isinstance(data, dict) and "cards" in data:
        cards = data["cards"]
    else:
        cards = data
    
    cards_by_id = {c["id"]: c for c in cards}
    
    # Load extracted items
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        items = list(reader)
    
    # Group items by order
    by_order = defaultdict(list)
    for item in items:
        by_order[item["order_id"]].append(item)
    
    # Evaluation metrics
    stats = {
        "total_orders": 0,
        "total_items": 0,
        "quantity_correct": 0,
        "quantity_present": 0,
        "dimensions_correct": 0,
        "dimensions_present": 0,
        "price_correct": 0,
        "price_present": 0,
        "order_class_correct": 0,
        "order_class_present": 0,
        "confidence_high": 0,
        "confidence_medium": 0,
        "confidence_low": 0,
        "issues": []
    }
    
    for order_id, line_items in by_order.items():
        if limit and stats["total_orders"] >= limit:
            break
            
        card = cards_by_id.get(order_id, {})
        desc = card.get("desc", "")
        
        if not desc.strip():
            continue
        
        stats["total_orders"] += 1
        
        # Extract ground truth from description
        gt_quantities = extract_quantities_from_text(desc)
        gt_dimensions = extract_dimensions_from_text(desc)
        gt_prices = extract_prices_from_text(desc)
        gt_classes = extract_order_class_from_text(desc)
        
        for item in line_items:
            stats["total_items"] += 1
            
            # Confidence
            conf = item.get("llm_confidence", "").lower()
            if conf == "high":
                stats["confidence_high"] += 1
            elif conf == "medium":
                stats["confidence_medium"] += 1
            else:
                stats["confidence_low"] += 1
            
            # Quantity check
            ext_qty = item.get("quantity")
            if ext_qty and ext_qty.strip():
                stats["quantity_present"] += 1
                try:
                    qty_val = int(float(ext_qty))
                    if qty_val in gt_quantities:
                        stats["quantity_correct"] += 1
                except:
                    pass
            
            # Dimensions check
            ext_w = item.get("width_in")
            ext_h = item.get("height_in")
            if ext_w and ext_w.strip():
                stats["dimensions_present"] += 1
                try:
                    w_val = float(ext_w)
                    h_val = float(ext_h) if ext_h and ext_h.strip() else None
                    # Check if dimensions match any ground truth
                    for gt_w, gt_h in gt_dimensions:
                        if abs(w_val - gt_w) < 0.5:
                            if h_val is None or abs(h_val - gt_h) < 0.5:
                                stats["dimensions_correct"] += 1
                                break
                except:
                    pass
            
            # Price check
            ext_price = item.get("price")
            if ext_price and ext_price.strip():
                stats["price_present"] += 1
                try:
                    price_val = float(ext_price)
                    for gt_price in gt_prices:
                        if abs(price_val - gt_price) < 0.01:
                            stats["price_correct"] += 1
                            break
                except:
                    pass
            
            # Order class check
            ext_class = item.get("order_class")
            if ext_class and ext_class.strip():
                stats["order_class_present"] += 1
                ext_class_lower = ext_class.lower()
                for gt_class in gt_classes:
                    if gt_class.lower() in ext_class_lower or ext_class_lower in gt_class.lower():
                        stats["order_class_correct"] += 1
                        break
    
    return stats


def print_report(stats: dict):
    """Print evaluation report."""
    print("\n" + "=" * 60)
    print("LINE ITEM EXTRACTION EVALUATION REPORT")
    print("=" * 60)
    
    print(f"\nOverview:")
    print(f"  Orders evaluated:    {stats['total_orders']}")
    print(f"  Line items extracted: {stats['total_items']}")
    
    print(f"\nConfidence Distribution:")
    total = stats["total_items"] or 1
    print(f"  High:   {stats['confidence_high']:4d} ({stats['confidence_high']/total*100:5.1f}%)")
    print(f"  Medium: {stats['confidence_medium']:4d} ({stats['confidence_medium']/total*100:5.1f}%)")
    print(f"  Low:    {stats['confidence_low']:4d} ({stats['confidence_low']/total*100:5.1f}%)")
    
    print(f"\nField Extraction Accuracy:")
    
    # Quantity
    qty_present = stats["quantity_present"] or 1
    print(f"  Quantity:")
    print(f"    Present:  {stats['quantity_present']:4d} / {stats['total_items']}")
    print(f"    Correct:  {stats['quantity_correct']:4d} / {stats['quantity_present']} ({stats['quantity_correct']/qty_present*100:.1f}%)")
    
    # Dimensions
    dim_present = stats["dimensions_present"] or 1
    print(f"  Dimensions:")
    print(f"    Present:  {stats['dimensions_present']:4d} / {stats['total_items']}")
    print(f"    Correct:  {stats['dimensions_correct']:4d} / {stats['dimensions_present']} ({stats['dimensions_correct']/dim_present*100:.1f}%)")
    
    # Price
    price_present = stats["price_present"] or 1
    print(f"  Price:")
    print(f"    Present:  {stats['price_present']:4d} / {stats['total_items']}")
    print(f"    Correct:  {stats['price_correct']:4d} / {stats['price_present']} ({stats['price_correct']/price_present*100:.1f}%)")
    
    # Order class
    class_present = stats["order_class_present"] or 1
    print(f"  Order Class:")
    print(f"    Present:  {stats['order_class_present']:4d} / {stats['total_items']}")
    print(f"    Correct:  {stats['order_class_correct']:4d} / {stats['order_class_present']} ({stats['order_class_correct']/class_present*100:.1f}%)")
    
    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Evaluate line item extraction quality")
    parser.add_argument("--csv", required=True, help="Path to extracted CSV file")
    parser.add_argument("--source", required=True, help="Path to source JSON file")
    parser.add_argument("--limit", type=int, help="Limit number of orders to evaluate")
    
    args = parser.parse_args()
    
    csv_path = Path(args.csv)
    source_path = Path(args.source)
    
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        return
    
    if not source_path.exists():
        print(f"Error: Source file not found: {source_path}")
        return
    
    stats = evaluate_extraction(csv_path, source_path, args.limit)
    print_report(stats)


if __name__ == "__main__":
    main()

