#!/usr/bin/env python3
"""
Trello Card Extraction Pipeline - Simplified Synchronous Version

Extracts from Trello cards:
1. Line items with pricing (price_type, unit_price, total_revenue)
2. Buyer information (names, emails)
3. Purchaser and order summary from card titles

Usage:
    python extract_trello_data.py --input LyB2G53h_cards.jsonl --batch-size 25

Author: Data Engineering Team
Date: December 2025
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).parent.parent / ".env")

from google import genai
from google.genai import types

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
LOCATION = os.environ.get("GCP_LOCATION", "us-central1")

DEFAULT_BATCH_SIZE = 25
DEFAULT_WORKERS = 5

# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(log_file: Optional[Path] = None) -> logging.Logger:
    """Configure logging with both file and console output."""
    logger = logging.getLogger("extraction")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []  # Clear any existing handlers
    
    # Console handler
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%H:%M:%S'
    ))
    logger.addHandler(console)
    
    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file, mode='w')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(message)s'
        ))
        logger.addHandler(file_handler)
    
    return logger

# =============================================================================
# SYSTEM PROMPT
# =============================================================================

SYSTEM_PROMPT = """Extract line items from signage orders. For each card return JSON:
{"card_id":"...", "items":[{"qty":1, "price":100.00, "price_type":"total", "desc":"item description"}], "buyer_name":"...", "buyer_email":"..."}

price_type: "per_unit" if price has "ea"/"each", otherwise "total".
Return JSON array, one object per card."""

# =============================================================================
# EXTRACTION FUNCTIONS
# =============================================================================

def extract_title_fields(card_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract purchaser and order_summary from card title."""
    if not card_name or "|" not in card_name:
        return None, None
    parts = [p.strip() for p in card_name.split("|")]
    purchaser = parts[0] if len(parts) > 0 and parts[0] else None
    order_summary = parts[1] if len(parts) > 1 and parts[1] else None
    return purchaser, order_summary


def calculate_prices(raw_price: Optional[float], quantity: Optional[int], price_type: str) -> Dict[str, Any]:
    """Calculate unit_price and total_revenue from extracted data."""
    if raw_price is None:
        return {'unit_price': None, 'total_revenue': None}
    
    if quantity is None or quantity <= 0:
        quantity = 1
    
    if price_type == 'per_unit':
        unit_price = raw_price
        total_revenue = round(unit_price * quantity, 2)
    else:
        total_revenue = raw_price
        unit_price = round(total_revenue / quantity, 2)
    
    return {'unit_price': unit_price, 'total_revenue': total_revenue}


def extract_batch(client: genai.Client, cards: List[Dict], logger: logging.Logger) -> List[Dict]:
    """Extract data from a batch of cards - SYNCHRONOUS."""
    
    # Prepare minimal batch input - only what we need
    batch_input = []
    for card in cards:
        batch_input.append({
            "id": card.get("id", ""),
            "name": card.get("name", ""),
            "desc": (card.get("desc", "") or "")[:2000]  # Truncate long descriptions
        })
    
    prompt = f"""Cards:\n{json.dumps(batch_input)}\n\nReturn JSON array."""

    try:
        # Simple synchronous API call
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.1,
                response_mime_type="application/json"
            )
        )
        
        # Parse response
        response_text = response.text.strip()
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            lines = [l for l in lines if not l.strip().startswith('```')]
            response_text = '\n'.join(lines)
        
        results = json.loads(response_text)
        if not isinstance(results, list):
            results = [results]
        
        # Build lookup by card_id
        result_lookup = {r.get('card_id'): r for r in results}
        
        # Process each card
        extracted_cards = []
        for card in cards:
            card_id = card.get('id', '')
            result = result_lookup.get(card_id, {})
            
            enriched = card.copy()
            
            # Title fields
            purchaser, order_summary = extract_title_fields(card.get('name', ''))
            enriched['purchaser'] = purchaser
            enriched['order_summary'] = order_summary
            
            # Buyer info (simplified)
            enriched['primary_buyer_name'] = result.get('buyer_name')
            enriched['primary_buyer_email'] = result.get('buyer_email')
            
            # Line items (simplified format)
            items = result.get('items', [])
            processed_items = []
            
            for idx, item in enumerate(items, 1):
                raw_price = item.get('price')
                if raw_price is not None:
                    try:
                        raw_price = float(raw_price)
                    except (ValueError, TypeError):
                        raw_price = None
                
                quantity = item.get('qty', 1)
                try:
                    quantity = int(quantity)
                except (ValueError, TypeError):
                    quantity = 1
                
                price_type = (item.get('price_type') or 'total').lower()
                calc = calculate_prices(raw_price, quantity, price_type)
                
                processed_items.append({
                    'line_index': idx,
                    'quantity': quantity,
                    'raw_price': raw_price,
                    'price_type': price_type,
                    'unit_price': calc['unit_price'],
                    'total_revenue': calc['total_revenue'],
                    'description': item.get('desc', '')
                })
            
            enriched['line_items'] = processed_items
            enriched['line_item_count'] = len(processed_items)
            extracted_cards.append(enriched)
        
        return extracted_cards
        
    except Exception as e:
        logger.error(f"Batch extraction error: {e}")
        # Return cards with error flag
        error_cards = []
        for card in cards:
            enriched = card.copy()
            enriched['extraction_error'] = str(e)
            enriched['line_items'] = []
            enriched['buyer_names'] = []
            enriched['buyer_emails'] = []
            error_cards.append(enriched)
        return error_cards


# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_extraction(
    input_path: Path,
    output_path: Path,
    batch_size: int,
    workers: int,
    limit: Optional[int],
    logger: logging.Logger
) -> Dict[str, Any]:
    """Run the extraction pipeline with parallel workers."""
    
    # Initialize client
    logger.info(f"Initializing Gemini client (project: {PROJECT_ID})")
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    # Load input
    logger.info(f"Loading: {input_path}")
    if input_path.suffix == '.jsonl':
        all_cards = []
        board_info = {}
        with open(input_path, 'r', encoding='utf-8') as f:
            for line in f:
                record = json.loads(line.strip())
                if record.get('_type') == 'board_info':
                    board_info = record
                elif record.get('_type') == 'card':
                    all_cards.append(record)
        data = {'cards': all_cards, **board_info}
    else:
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        all_cards = data.get('cards', [])
    
    logger.info(f"Loaded {len(all_cards):,} cards")
    
    # Apply limit
    if limit:
        cards = all_cards[:limit]
        logger.info(f"Limited to {len(cards)} cards")
    else:
        cards = all_cards
    
    # Create batches
    batches = [(i, cards[i:i + batch_size]) for i in range(0, len(cards), batch_size)]
    total_batches = len(batches)
    
    logger.info(f"Processing {len(cards):,} cards in {total_batches} batches with {workers} workers")
    logger.info("=" * 60)
    
    # Process batches in parallel
    all_extracted = [None] * len(cards)  # Pre-allocate to maintain order
    start_time = time.time()
    error_count = 0
    completed = 0
    
    def process_batch(batch_info):
        """Worker function for parallel processing."""
        start_idx, batch = batch_info
        batch_num = start_idx // batch_size + 1
        return start_idx, batch_num, extract_batch(client, batch, logger)
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Submit all batches
        futures = {executor.submit(process_batch, b): b for b in batches}
        
        # Process results as they complete
        for future in as_completed(futures):
            try:
                start_idx, batch_num, extracted = future.result()
                
                # Store results in correct position
                for i, card in enumerate(extracted):
                    all_extracted[start_idx + i] = card
                
                # Count errors
                batch_errors = sum(1 for c in extracted if c.get('extraction_error'))
                error_count += batch_errors
                completed += 1
                
                # Progress stats
                elapsed = time.time() - start_time
                processed = completed * batch_size
                rate = processed / elapsed * 60 if elapsed > 0 else 0
                remaining = len(cards) - processed
                eta = remaining / (processed / elapsed) if processed > 0 else 0
                
                logger.info(
                    f"Batch {completed}/{total_batches} done | "
                    f"Progress: {min(processed, len(cards)):,}/{len(cards):,} | "
                    f"Rate: {rate:.0f}/min | "
                    f"ETA: {eta/60:.1f}m | "
                    f"Errors: {error_count}"
                )
            except Exception as e:
                logger.error(f"Batch failed: {e}")
                error_count += batch_size
                completed += 1
    
    # Remove any None values (shouldn't happen but safety check)
    all_extracted = [c for c in all_extracted if c is not None]
    
    # Calculate final stats
    elapsed = time.time() - start_time
    total_line_items = sum(len(c.get('line_items', [])) for c in all_extracted)
    total_revenue = sum(
        sum(item.get('total_revenue', 0) or 0 for item in c.get('line_items', []))
        for c in all_extracted
    )
    cards_with_buyer = sum(1 for c in all_extracted if c.get('primary_buyer_name'))
    
    stats = {
        'total_cards': len(cards),
        'processed': len(all_extracted),
        'errors': error_count,
        'line_items': total_line_items,
        'total_revenue': total_revenue,
        'cards_with_buyer': cards_with_buyer,
        'elapsed_seconds': elapsed
    }
    
    # Save output
    data['cards'] = all_extracted
    data['extraction_metadata'] = {
        'timestamp': datetime.now().isoformat(),
        'model': MODEL_ID,
        'batch_size': batch_size,
        'stats': stats
    }
    
    logger.info(f"Saving to: {output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return stats


def generate_line_items_csv(input_path: Path, output_path: Path, logger: logging.Logger):
    """Generate CSV of line items."""
    logger.info(f"Generating CSV: {output_path}")
    
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    fieldnames = [
        'order_id', 'line_index', 'location_group', 'order_class', 
        'business_line', 'job_type', 'quantity',
        'unit_price', 'total_revenue', 'raw_price', 'price_type',
        'width_in', 'height_in', 'material', 'colour', 'description',
        'raw_line_text', 'raw_price_text', 'confidence',
        'purchaser', 'order_summary', 'primary_buyer_name', 'primary_buyer_email'
    ]
    
    rows = []
    for card in data.get('cards', []):
        card_id = card.get('id', '')
        for item in card.get('line_items', []):
            row = {
                'order_id': card_id,
                'purchaser': card.get('purchaser', ''),
                'order_summary': card.get('order_summary', ''),
                'primary_buyer_name': card.get('primary_buyer_name', ''),
                'primary_buyer_email': card.get('primary_buyer_email', ''),
                **{k: item.get(k) for k in fieldnames if k in item}
            }
            rows.append(row)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    
    logger.info(f"Written {len(rows):,} line items")


def generate_review_html(input_path: Path, output_path: Path, sample_size: int = 100):
    """Generate HTML review document."""
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    cards = data.get('cards', [])[:sample_size]
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Extraction Review</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 20px; background: #f5f5f5; }}
        .card {{ background: white; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .header {{ background: #667eea; color: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .line-item {{ background: #f9f9f9; padding: 10px; margin: 10px 0; border-left: 3px solid #667eea; }}
        .revenue {{ color: #28a745; font-weight: bold; }}
        pre {{ background: #f0f0f0; padding: 10px; overflow-x: auto; white-space: pre-wrap; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Extraction Review</h1>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        <p>Sample: {len(cards)} cards</p>
    </div>
"""
    
    for i, card in enumerate(cards, 1):
        total_revenue = sum(item.get('total_revenue', 0) or 0 for item in card.get('line_items', []))
        html += f"""
    <div class="card">
        <h3>Card {i}: {(card.get('name', 'N/A') or 'N/A')[:60]}...</h3>
        <p><strong>ID:</strong> {card.get('id')}</p>
        <p><strong>Purchaser:</strong> {card.get('purchaser', 'N/A')}</p>
        <p><strong>Buyer:</strong> {card.get('primary_buyer_name', 'N/A')} ({card.get('primary_buyer_email', 'N/A')})</p>
        <p><strong>Total Revenue:</strong> <span class="revenue">${total_revenue:,.2f}</span></p>
        <h4>Description:</h4>
        <pre>{(card.get('desc', '') or 'No description')[:500]}</pre>
        <h4>Line Items ({len(card.get('line_items', []))}):</h4>
"""
        for item in card.get('line_items', []):
            html += f"""
        <div class="line-item">
            <p><strong>#{item.get('line_index', '?')}</strong> | 
            Qty: {item.get('quantity', '?')} | Type: {item.get('price_type', '?')} |
            <span class="revenue">${item.get('total_revenue', 0) or 0:,.2f}</span></p>
            <p><em>{(item.get('description', '') or '')[:150]}</em></p>
        </div>
"""
        html += "</div>"
    
    html += "</body></html>"
    
    with open(output_path, 'w') as f:
        f.write(html)


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Extract data from Trello cards")
    parser.add_argument("--input", "-i", required=True, help="Input JSON/JSONL file")
    parser.add_argument("--output", "-o", help="Output JSON file")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Parallel workers")
    parser.add_argument("--limit", type=int, help="Limit cards to process")
    parser.add_argument("--csv", action="store_true", help="Generate CSV")
    parser.add_argument("--review", action="store_true", help="Generate HTML review")
    
    args = parser.parse_args()
    
    if not PROJECT_ID:
        print("ERROR: BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT not set")
        sys.exit(1)
    
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {input_path}")
        sys.exit(1)
    
    output_path = Path(args.output) if args.output else input_path.parent / f"{input_path.stem}_extracted.json"
    log_path = output_path.parent / f"{output_path.stem}.log"
    
    logger = setup_logging(log_path)
    
    logger.info("=" * 60)
    logger.info("TRELLO EXTRACTION PIPELINE")
    logger.info("=" * 60)
    logger.info(f"Input:   {input_path}")
    logger.info(f"Output:  {output_path}")
    logger.info(f"Model:   {MODEL_ID}")
    logger.info(f"Batch:   {args.batch_size}")
    logger.info(f"Workers: {args.workers}")
    logger.info("=" * 60)
    
    try:
        stats = run_extraction(
            input_path=input_path,
            output_path=output_path,
            batch_size=args.batch_size,
            workers=args.workers,
            limit=args.limit,
            logger=logger
        )
        
        logger.info("=" * 60)
        logger.info("COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Cards: {stats['processed']:,}")
        logger.info(f"Errors: {stats['errors']}")
        logger.info(f"Line items: {stats['line_items']:,}")
        logger.info(f"Revenue: ${stats['total_revenue']:,.2f}")
        logger.info(f"Time: {stats['elapsed_seconds']/60:.1f} minutes")
        
        if args.csv:
            csv_path = output_path.parent / f"{output_path.stem}_lineitems.csv"
            generate_line_items_csv(output_path, csv_path, logger)
        
        if args.review:
            html_path = output_path.parent / f"{output_path.stem}_review.html"
            generate_review_html(output_path, html_path)
            logger.info(f"Review: {html_path}")
        
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
