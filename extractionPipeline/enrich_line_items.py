#!/usr/bin/env python3
"""
Enrich Line Items with Business Line, Material, and Dimensions

Processes LINE ITEMS in batches with proper logging.

Usage:
    python enrich_line_items.py --input LyB2G53h_cards_extracted.json --workers 5 --batch-size 25
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from google import genai
from google.genai import types

PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
MODEL_ID = "gemini-2.5-flash-lite"
LOCATION = "us-central1"

# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(log_file: Path) -> logging.Logger:
    """Configure logging with both file and console output."""
    logger = logging.getLogger("enrichment")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []  # Clear existing handlers
    
    # Console handler (INFO level) - with immediate flush
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    ))
    logger.addHandler(console)
    
    # File handler (DEBUG level)
    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s'
    ))
    logger.addHandler(file_handler)
    
    return logger

# =============================================================================
# PROMPT
# =============================================================================

ENRICH_PROMPT = """Classify line items from a signage company.

For each line item, determine:

1. **business_line** - Choose ONE:
   - "Signage" - Signs, banners, decals, vehicle wraps, channel letters, pylons, ACP panels, coroplast, building signage, vinyl graphics
   - "Printing" - Business cards, flyers, brochures, booklets, invoices, forms, apparel printing, promotional items, labels
   - "Engraving" - Engraved plaques, nameplates, trophies, awards, laser-cut items, etched materials

2. **material** - Extract the material (e.g., "Aluminum", "Acrylic", "Vinyl", "Coroplast", "14PT Coated", "ACP", "Foamcore") or null

3. **dimensions** - Extract dimensions as string (e.g., "36x24", "3.5x2", "96x48") or null

Return JSON array matching input order:
[{"business_line": "Signage", "material": "Vinyl", "dimensions": "36x24"}, ...]
"""

# =============================================================================
# ENRICHMENT FUNCTIONS
# =============================================================================

def enrich_batch(client: genai.Client, items_batch: list, logger: logging.Logger) -> list:
    """Enrich a batch of line items."""
    
    batch_input = []
    for item_info in items_batch:
        batch_input.append({
            "description": item_info['description'][:200],
            "quantity": item_info['quantity'],
            "revenue": item_info['revenue']
        })
    
    prompt = f"""Classify these {len(batch_input)} line items:

{json.dumps(batch_input)}

Return JSON array with business_line, material, dimensions for each (same order as input)."""

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=ENRICH_PROMPT,
                temperature=0.1,
                response_mime_type="application/json"
            )
        )
        
        text = response.text.strip()
        if text.startswith('```'):
            text = '\n'.join(l for l in text.split('\n') if not l.strip().startswith('```'))
        
        results = json.loads(text)
        if not isinstance(results, list):
            results = [results]
        
        return results
    except Exception as e:
        logger.debug(f"Batch error: {e}")
        return [{"error": str(e)}] * len(items_batch)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--output", "-o")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path
    log_path = input_path.parent / "enrichment.log"
    
    # Setup logging
    logger = setup_logging(log_path)
    
    logger.info("=" * 60)
    logger.info("LINE ITEM ENRICHMENT")
    logger.info("=" * 60)
    logger.info(f"Input:      {input_path}")
    logger.info(f"Output:     {output_path}")
    logger.info(f"Log:        {log_path}")
    logger.info(f"Model:      {MODEL_ID}")
    logger.info(f"Workers:    {args.workers}")
    logger.info(f"Batch size: {args.batch_size}")
    logger.info("=" * 60)
    
    # Load
    logger.info(f"Loading data...")
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    cards = data.get('cards', [])
    
    # Build flat list of all line items with references
    all_items = []
    for card_idx, card in enumerate(cards):
        for item_idx, item in enumerate(card.get('line_items', [])):
            all_items.append({
                'card_idx': card_idx,
                'item_idx': item_idx,
                'description': item.get('description', '') or '',
                'quantity': item.get('quantity', 1),
                'revenue': item.get('total_revenue', 0)
            })
    
    logger.info(f"Total line items: {len(all_items):,}")
    
    # Create batches
    batches = []
    for i in range(0, len(all_items), args.batch_size):
        batches.append(all_items[i:i + args.batch_size])
    
    logger.info(f"Batches: {len(batches)} (batch size {args.batch_size})")
    logger.info("=" * 60)
    
    # Initialize client
    logger.info("Initializing Gemini client...")
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    # Process batches
    enriched_count = 0
    error_count = 0
    completed_batches = 0
    start_time = time.time()
    
    def process_batch(batch_info):
        batch_idx, batch = batch_info
        results = enrich_batch(client, batch, logger)
        return batch_idx, batch, results
    
    indexed_batches = list(enumerate(batches))
    
    logger.info(f"Starting enrichment with {args.workers} workers...")
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_batch, ib): ib for ib in indexed_batches}
        
        for future in as_completed(futures):
            try:
                batch_idx, batch, results = future.result()
                
                # Apply results
                for i, (item_info, result) in enumerate(zip(batch, results)):
                    if result.get('error'):
                        error_count += 1
                        continue
                    
                    card_idx = item_info['card_idx']
                    item_idx = item_info['item_idx']
                    
                    item = cards[card_idx]['line_items'][item_idx]
                    item['business_line'] = result.get('business_line')
                    item['material'] = result.get('material')
                    item['dimensions'] = result.get('dimensions')
                    enriched_count += 1
                
                completed_batches += 1
                
                # Log progress every 20 batches
                if completed_batches % 20 == 0 or completed_batches == len(batches):
                    elapsed = time.time() - start_time
                    items_done = completed_batches * args.batch_size
                    rate = items_done / elapsed * 60 if elapsed > 0 else 0
                    eta = (len(all_items) - items_done) / (items_done / elapsed) if items_done > 0 else 0
                    
                    logger.info(
                        f"Progress: {completed_batches}/{len(batches)} batches | "
                        f"{enriched_count:,} enriched | "
                        f"Rate: {rate:.0f}/min | "
                        f"ETA: {eta/60:.1f}m | "
                        f"Errors: {error_count}"
                    )
                    
            except Exception as e:
                logger.error(f"Batch exception: {e}")
                error_count += args.batch_size
                completed_batches += 1
    
    # Metadata
    data['enrichment_metadata'] = {
        'timestamp': datetime.now().isoformat(),
        'items_total': len(all_items),
        'items_enriched': enriched_count,
        'errors': error_count,
        'fields_added': ['business_line', 'material', 'dimensions']
    }
    
    # Save
    logger.info("=" * 60)
    logger.info(f"Saving to: {output_path}")
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Summary
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("ENRICHMENT COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Line items enriched: {enriched_count:,} / {len(all_items):,} ({enriched_count/len(all_items)*100:.1f}%)")
    logger.info(f"Errors: {error_count}")
    logger.info(f"Time: {elapsed/60:.1f} minutes")
    
    # Business line distribution
    logger.info("")
    logger.info("BUSINESS LINE DISTRIBUTION:")
    from collections import Counter
    bl_revenue = Counter()
    bl_count = Counter()
    for card in cards:
        for item in card.get('line_items', []):
            bl = item.get('business_line') or 'Not classified'
            rev = item.get('total_revenue', 0) or 0
            bl_revenue[bl] += rev
            bl_count[bl] += 1
    
    for bl in ['Signage', 'Printing', 'Engraving', 'Not classified']:
        logger.info(f"  {bl}: {bl_count[bl]:,} items, ${bl_revenue[bl]:,.2f}")


if __name__ == "__main__":
    main()
