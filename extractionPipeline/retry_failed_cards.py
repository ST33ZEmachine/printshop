#!/usr/bin/env python3
"""
Retry Failed Cards - Re-process cards that failed in the initial extraction.

This script reads the error log from the initial run and re-processes
only the failed cards with a smaller batch size for better reliability.

Usage:
    python retry_failed_cards.py

The script will:
1. Load the error log (parse_errors_full.jsonl)
2. Extract the failed order_ids
3. Re-run extraction on just those cards
4. Merge results with the existing output
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Import from main script
from parse_orders_to_line_items import (
    extract_line_items_batch,
    flatten_line_items,
    validate_line_item,
    CSV_COLUMNS,
    SYSTEM_PROMPT,
    MODEL_ID,
    LOCATION,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")

# Smaller batch size for retry - more reliable
RETRY_BATCH_SIZE = 15


def load_failed_order_ids(error_file: Path) -> set:
    """Load order IDs that failed in the initial run."""
    failed_ids = set()
    with open(error_file) as f:
        for line in f:
            error = json.loads(line)
            failed_ids.add(error['order_id'])
    return failed_ids


def load_source_cards(source_file: Path, order_ids: set) -> list:
    """Load only the cards that need to be retried."""
    with open(source_file) as f:
        data = json.load(f)
    
    cards = data.get('cards', [])
    return [c for c in cards if c['id'] in order_ids]


def write_csv_append(data: list, filepath: Path, columns: list):
    """Append data to existing CSV file."""
    with open(filepath, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        for row in data:
            clean_row = {col: row.get(col) for col in columns}
            writer.writerow(clean_row)


def main():
    parser = argparse.ArgumentParser(description="Retry failed card extractions")
    parser.add_argument(
        "--errors",
        type=str,
        default="parse_errors_full.jsonl",
        help="Error log from initial run"
    )
    parser.add_argument(
        "--source",
        type=str,
        default="bourquin_05122025_snapshot.json",
        help="Source JSON file"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="line_items_full.csv",
        help="Output CSV to append retried items to (default: line_items_full.csv)"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        default=True,
        help="Append to existing CSV instead of overwriting (default: True)"
    )
    parser.add_argument(
        "--new-file",
        action="store_true",
        help="Write to a new file instead of appending"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=RETRY_BATCH_SIZE,
        help=f"Batch size for retry (default: {RETRY_BATCH_SIZE})"
    )
    parser.add_argument(
        "--filter-has-order",
        action="store_true",
        help="Only retry cards with Supply/Install keywords"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be retried without making API calls"
    )
    
    args = parser.parse_args()
    
    # Resolve paths
    script_dir = Path(__file__).parent
    error_path = script_dir / args.errors
    source_path = script_dir / args.source
    output_path = script_dir / args.output
    
    # Load failed order IDs
    logger.info(f"Loading failed order IDs from {error_path}...")
    failed_ids = load_failed_order_ids(error_path)
    logger.info(f"Found {len(failed_ids)} failed orders")
    
    # Load source cards
    logger.info(f"Loading source cards...")
    cards = load_source_cards(source_path, failed_ids)
    logger.info(f"Loaded {len(cards)} cards to retry")
    
    # Filter to cards with order keywords if requested
    if args.filter_has_order:
        cards = [
            c for c in cards 
            if 'supply' in c.get('desc', '').lower() or 'install' in c.get('desc', '').lower()
        ]
        logger.info(f"Filtered to {len(cards)} cards with Supply/Install keywords")
    
    # Dry run
    if args.dry_run:
        num_batches = (len(cards) + args.batch_size - 1) // args.batch_size
        logger.info(f"\n=== DRY RUN ===")
        logger.info(f"Cards to retry: {len(cards)}")
        logger.info(f"Batch size: {args.batch_size}")
        logger.info(f"Total batches: {num_batches}")
        logger.info(f"Estimated API calls: {num_batches}")
        logger.info(f"Estimated cost: ~${num_batches * 0.001:.2f}")
        return
    
    # Validate environment
    if not PROJECT_ID:
        logger.error("GOOGLE_CLOUD_PROJECT not set")
        sys.exit(1)
    
    # Initialize Gemini client
    from google import genai
    logger.info("Initializing Gemini client...")
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    # Process in batches
    logger.info(f"Starting retry with batch size {args.batch_size}...")
    start_time = time.time()
    
    all_results = []
    all_errors = []
    batch_size = args.batch_size
    num_batches = (len(cards) + batch_size - 1) // batch_size
    
    for i in range(0, len(cards), batch_size):
        batch = cards[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        
        logger.info(f"Batch {batch_num}/{num_batches} ({len(batch)} cards)")
        
        results, errors = extract_line_items_batch(client, batch, MODEL_ID)
        all_results.extend(results)
        all_errors.extend(errors)
        
        total_items = sum(len(r.get('line_items', [])) for r in all_results)
        logger.info(f"  -> {total_items} total line items, {len(all_errors)} errors")
        
        if batch_num < num_batches:
            time.sleep(1)
    
    elapsed = time.time() - start_time
    
    # Flatten and write output
    flattened = flatten_line_items(all_results)
    
    # Determine write mode
    append_mode = args.append and not args.new_file and output_path.exists()
    
    if append_mode:
        logger.info(f"Appending {len(flattened)} items to existing {output_path}...")
        with open(output_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction='ignore')
            for row in flattened:
                clean_row = {col: row.get(col) for col in CSV_COLUMNS}
                writer.writerow(clean_row)
    else:
        logger.info(f"Writing {len(flattened)} items to new file {output_path}...")
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction='ignore')
            writer.writeheader()
            for row in flattened:
                clean_row = {col: row.get(col) for col in CSV_COLUMNS}
                writer.writerow(clean_row)
    
    # Validation against ground truth
    logger.info("Validating extractions against source text...")
    
    # Build card lookup for validation
    cards_by_id = {c['id']: c for c in cards}
    
    validation_stats = {
        'total_items': len(flattened),
        'price_present': 0,
        'price_validated': 0,
        'quantity_present': 0,
        'has_order_class': 0,
        'high_confidence': 0,
        'medium_confidence': 0,
        'low_confidence': 0,
    }
    
    for item in flattened:
        if item.get('price'):
            validation_stats['price_present'] += 1
            if item.get('price_validated') == True or item.get('price_validated') == 'True':
                validation_stats['price_validated'] += 1
        if item.get('quantity'):
            validation_stats['quantity_present'] += 1
        if item.get('order_class'):
            validation_stats['has_order_class'] += 1
        
        conf = str(item.get('llm_confidence', '')).lower()
        if conf == 'high':
            validation_stats['high_confidence'] += 1
        elif conf == 'medium':
            validation_stats['medium_confidence'] += 1
        else:
            validation_stats['low_confidence'] += 1
    
    # Summary
    orders_with_items = sum(1 for r in all_results if r.get('line_items'))
    
    logger.info("\n" + "=" * 60)
    logger.info("RETRY COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Cards retried:       {len(cards)}")
    logger.info(f"Cards with items:    {orders_with_items}")
    logger.info(f"Still failing:       {len(all_errors)}")
    logger.info(f"New line items:      {len(flattened)}")
    logger.info(f"Time elapsed:        {elapsed:.1f}s")
    logger.info("-" * 60)
    logger.info("VALIDATION RESULTS:")
    if validation_stats['total_items'] > 0:
        ti = validation_stats['total_items']
        pp = validation_stats['price_present']
        pv = validation_stats['price_validated']
        logger.info(f"  Items with price:     {pp} ({100*pp/ti:.1f}%)")
        if pp > 0:
            logger.info(f"  Prices validated:     {pv}/{pp} ({100*pv/pp:.1f}%)")
        logger.info(f"  Items with quantity:  {validation_stats['quantity_present']} ({100*validation_stats['quantity_present']/ti:.1f}%)")
        logger.info(f"  Items with class:     {validation_stats['has_order_class']} ({100*validation_stats['has_order_class']/ti:.1f}%)")
        logger.info(f"  Confidence: High={validation_stats['high_confidence']}, Med={validation_stats['medium_confidence']}, Low={validation_stats['low_confidence']}")
    logger.info("=" * 60)
    if append_mode:
        logger.info(f"APPENDED to: {output_path}")
    else:
        logger.info(f"Output: {output_path}")
    
    # Write remaining errors
    if all_errors:
        error_out = script_dir / "parse_errors_retry.jsonl"
        with open(error_out, 'w') as f:
            for e in all_errors:
                f.write(json.dumps(e) + '\n')
        logger.info(f"Remaining errors: {error_out}")


if __name__ == "__main__":
    main()

