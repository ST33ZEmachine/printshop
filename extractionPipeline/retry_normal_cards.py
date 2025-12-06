#!/usr/bin/env python3
"""
Retry the 498 "normal" cards that failed with batch size 10.
"""

import csv
import json
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from parse_orders_to_line_items import (
    extract_line_items_batch,
    flatten_line_items,
    CSV_COLUMNS,
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
BATCH_SIZE = 10  # Smaller for reliability

def main():
    script_dir = Path(__file__).parent
    
    # Load normal card IDs
    with open(script_dir / 'normal_card_ids.txt') as f:
        normal_ids = set(line.strip() for line in f if line.strip())
    
    logger.info(f"Loaded {len(normal_ids)} normal card IDs to retry")
    
    # Load source cards
    with open(script_dir / 'bourquin_05122025_snapshot.json') as f:
        data = json.load(f)
    
    cards = [c for c in data['cards'] if c['id'] in normal_ids]
    logger.info(f"Found {len(cards)} cards in source")
    
    # Initialize Gemini
    from google import genai
    logger.info("Initializing Gemini client...")
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    # Process in batches
    logger.info(f"Processing with batch size {BATCH_SIZE}...")
    start_time = time.time()
    
    all_results = []
    all_errors = []
    num_batches = (len(cards) + BATCH_SIZE - 1) // BATCH_SIZE
    
    for i in range(0, len(cards), BATCH_SIZE):
        batch = cards[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        
        logger.info(f"Batch {batch_num}/{num_batches} ({len(batch)} cards)")
        
        results, errors = extract_line_items_batch(client, batch, MODEL_ID)
        all_results.extend(results)
        all_errors.extend(errors)
        
        total_items = sum(len(r.get('line_items', [])) for r in all_results)
        logger.info(f"  -> {total_items} items, {len(all_errors)} errors")
        
        if batch_num < num_batches:
            time.sleep(0.5)
    
    elapsed = time.time() - start_time
    
    # Flatten results
    flattened = flatten_line_items(all_results)
    
    # Append to main CSV
    output_path = script_dir / 'line_items_full.csv'
    logger.info(f"Appending {len(flattened)} items to {output_path}...")
    
    with open(output_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction='ignore')
        for row in flattened:
            clean_row = {col: row.get(col) for col in CSV_COLUMNS}
            writer.writerow(clean_row)
    
    # Validation stats
    price_present = sum(1 for i in flattened if i.get('price'))
    price_validated = sum(1 for i in flattened if i.get('price') and (i.get('price_validated') == True or i.get('price_validated') == 'True'))
    high_conf = sum(1 for i in flattened if str(i.get('llm_confidence', '')).lower() == 'high')
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("RETRY COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Cards processed:     {len(cards)}")
    logger.info(f"Cards with items:    {sum(1 for r in all_results if r.get('line_items'))}")
    logger.info(f"Still failing:       {len(all_errors)}")
    logger.info(f"New line items:      {len(flattened)}")
    logger.info(f"Time elapsed:        {elapsed:.1f}s")
    logger.info("-" * 60)
    logger.info("VALIDATION:")
    if flattened:
        logger.info(f"  Prices present:    {price_present}/{len(flattened)} ({100*price_present/len(flattened):.1f}%)")
        if price_present:
            logger.info(f"  Prices validated:  {price_validated}/{price_present} ({100*price_validated/price_present:.1f}%)")
        logger.info(f"  High confidence:   {high_conf}/{len(flattened)} ({100*high_conf/len(flattened):.1f}%)")
    logger.info("=" * 60)
    logger.info(f"APPENDED to: {output_path}")
    
    # Save remaining errors
    if all_errors:
        error_path = script_dir / 'parse_errors_final.jsonl'
        with open(error_path, 'w') as f:
            for e in all_errors:
                f.write(json.dumps(e) + '\n')
        logger.info(f"Remaining errors: {error_path}")


if __name__ == "__main__":
    main()

