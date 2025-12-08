#!/usr/bin/env python3
"""
Audit Top Orders for Business Card Pricing Issues

Uses parallel workers (same pattern as extract_trello_data.py).

Usage:
    python audit_business_cards.py --input LyB2G53h_cards_extracted.json --top 2000 --workers 5
"""

import argparse
import json
import os
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

AUDIT_PROMPT = """Audit for business card pricing errors.

ISSUE: Business cards sold in PACKS (250, 500, 1000). "Each" means per PACK, not per card.
ERROR: "500 business cards @ $45 each" → Wrong: 500×$45=$22,500. Correct: $45 total.

For each line item, return:
{"line_index": 1, "is_business_card": true/false, "has_pricing_error": true/false, "reason": "..."}

Mark has_pricing_error=true ONLY if: business card order + per_unit pricing + pack quantity + unreasonably high revenue.
Return JSON array."""


def audit_single_card(client: genai.Client, card: dict) -> dict:
    """Audit a single card for business card issues."""
    card_id = card.get("id")
    
    items_info = []
    for item in card.get("line_items", []):
        items_info.append({
            "line_index": item.get("line_index"),
            "description": item.get("description", "")[:200],
            "quantity": item.get("quantity"),
            "price_type": item.get("price_type"),
            "unit_price": item.get("unit_price"),
            "total_revenue": item.get("total_revenue")
        })
    
    if not items_info:
        return {"card_id": card_id, "audits": []}
    
    prompt = f"""Card description: {(card.get('desc', '') or '')[:800]}

Line items:
{json.dumps(items_info)}

Return JSON array of audits for each line item."""

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=AUDIT_PROMPT,
                temperature=0.1,
                response_mime_type="application/json"
            )
        )
        
        text = response.text.strip()
        if text.startswith('```'):
            text = '\n'.join(l for l in text.split('\n') if not l.strip().startswith('```'))
        
        audits = json.loads(text)
        if not isinstance(audits, list):
            audits = [audits]
        
        return {"card_id": card_id, "audits": audits}
    except Exception as e:
        return {"card_id": card_id, "audits": [], "error": str(e)}


def apply_corrections(card: dict, audits: list) -> int:
    """Apply corrections based on audit results. Returns number of corrections."""
    corrections = 0
    audit_lookup = {a.get("line_index"): a for a in audits if isinstance(a, dict)}
    
    for item in card.get("line_items", []):
        audit = audit_lookup.get(item.get("line_index"), {})
        
        if audit.get("has_pricing_error") and audit.get("is_business_card"):
            if item.get("price_type") == "per_unit" and item.get("raw_price"):
                old_revenue = item.get("total_revenue", 0)
                
                # Fix: raw_price IS the total, not per-unit
                item["price_type"] = "total"
                item["total_revenue"] = item.get("raw_price")
                item["unit_price"] = round(item["raw_price"] / max(item.get("quantity", 1), 1), 4)
                item["audit_log"] = "business card issue"
                item["audit_reason"] = audit.get("reason", "")[:100]
                item["original_revenue"] = old_revenue
                corrections += 1
    
    return corrections


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--output", "-o")
    parser.add_argument("--top", type=int, default=2000)
    parser.add_argument("--workers", type=int, default=5)
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.parent / f"{input_path.stem}_audited.json"
    
    print("=" * 60)
    print("BUSINESS CARD PRICING AUDIT")
    print("=" * 60)
    print(f"Workers: {args.workers}")
    
    # Load
    print(f"Loading: {input_path}")
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    cards = data.get('cards', [])
    
    # Sort by revenue
    for card in cards:
        card['_total_revenue'] = sum(item.get('total_revenue', 0) or 0 for item in card.get('line_items', []))
    
    cards_sorted = sorted(cards, key=lambda c: c['_total_revenue'], reverse=True)
    cards_to_audit = cards_sorted[:args.top]
    
    print(f"Auditing top {len(cards_to_audit)} orders")
    print(f"Revenue range: ${cards_to_audit[0]['_total_revenue']:,.2f} to ${cards_to_audit[-1]['_total_revenue']:,.2f}")
    print("=" * 60)
    
    # Initialize client
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    
    # Process with parallel workers
    total_corrections = 0
    cards_corrected = 0
    completed = 0
    start_time = time.time()
    
    def process_card(card):
        result = audit_single_card(client, card)
        return card, result
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_card, card): card for card in cards_to_audit}
        
        for future in as_completed(futures):
            try:
                card, result = future.result()
                audits = result.get("audits", [])
                
                corrections = apply_corrections(card, audits)
                total_corrections += corrections
                if corrections > 0:
                    cards_corrected += 1
                
                completed += 1
                
                if completed % 50 == 0 or completed == len(cards_to_audit):
                    elapsed = time.time() - start_time
                    rate = completed / elapsed * 60 if elapsed > 0 else 0
                    print(f"Progress: {completed}/{len(cards_to_audit)} | Corrections: {total_corrections} | Rate: {rate:.0f}/min")
                    
            except Exception as e:
                print(f"Error: {e}")
                completed += 1
    
    # Cleanup
    for card in cards:
        card.pop('_total_revenue', None)
    
    # Metadata
    data['audit_metadata'] = {
        'timestamp': datetime.now().isoformat(),
        'cards_audited': len(cards_to_audit),
        'cards_corrected': cards_corrected,
        'total_corrections': total_corrections
    }
    
    # Save
    print("=" * 60)
    print(f"Saving: {output_path}")
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print("=" * 60)
    print("AUDIT COMPLETE")
    print(f"Cards audited: {len(cards_to_audit)}")
    print(f"Cards corrected: {cards_corrected}")
    print(f"Line items corrected: {total_corrections}")
    print(f"Time: {(time.time() - start_time)/60:.1f} min")
    
    # Show examples
    if total_corrections > 0:
        print("\nSample corrections:")
        shown = 0
        for card in cards_to_audit:
            for item in card.get('line_items', []):
                if item.get('audit_log') == 'business card issue':
                    print(f"  ${item.get('original_revenue', 0):,.0f} → ${item.get('total_revenue', 0):,.2f}: {item.get('audit_reason', '')[:50]}")
                    shown += 1
                    if shown >= 10:
                        break
            if shown >= 10:
                break


if __name__ == "__main__":
    main()
