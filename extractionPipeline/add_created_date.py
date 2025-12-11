#!/usr/bin/env python3
"""
Add 'date_created' field to extracted Trello cards.

Trello card IDs start with 8 hex characters representing a Unix timestamp.
This script extracts that timestamp and adds a human-readable date.

Usage:
    python add_created_date.py --input LyB2G53h_cards_extracted.json
"""

import argparse
import json
from datetime import datetime
from pathlib import Path


def extract_created_date(card_id: str) -> dict:
    """
    Extract creation timestamp from Trello card ID.
    
    First 8 hex characters = Unix timestamp of card creation.
    Returns dict with timestamp and formatted dates.
    """
    if not card_id or len(card_id) < 8:
        return {'date_created': None, 'year_created': None, 'month_created': None}
    
    try:
        # First 8 chars are hex timestamp
        hex_timestamp = card_id[:8]
        unix_timestamp = int(hex_timestamp, 16)
        
        # Convert to datetime
        dt = datetime.fromtimestamp(unix_timestamp)
        
        return {
            'date_created': dt.strftime('%Y-%m-%d'),
            'datetime_created': dt.isoformat(),
            'year_created': dt.year,
            'month_created': dt.month,
            'year_month': dt.strftime('%Y-%m'),
            'unix_timestamp': unix_timestamp
        }
    except (ValueError, OSError) as e:
        # Invalid hex or timestamp out of range
        return {'date_created': None, 'year_created': None, 'month_created': None}


def main():
    parser = argparse.ArgumentParser(description="Add created date to Trello cards")
    parser.add_argument("--input", "-i", required=True, help="Input JSON file")
    parser.add_argument("--output", "-o", help="Output JSON file (default: overwrite input)")
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path
    
    print(f"Loading: {input_path}")
    with open(input_path, 'r') as f:
        data = json.load(f)
    
    cards = data.get('cards', [])
    print(f"Processing {len(cards):,} cards...")
    
    # Add date fields to each card
    for card in cards:
        card_id = card.get('id', '')
        date_info = extract_created_date(card_id)
        card.update(date_info)
    
    # Show sample
    print("\nSample dates extracted:")
    for card in cards[:5]:
        print(f"  {card.get('id', '?')[:8]} -> {card.get('date_created')} ({card.get('year_month')})")
    
    # Show year distribution
    years = {}
    for card in cards:
        year = card.get('year_created')
        if year:
            years[year] = years.get(year, 0) + 1
    
    print("\nCards by year:")
    for year in sorted(years.keys()):
        print(f"  {year}: {years[year]:,} cards")
    
    # Save
    print(f"\nSaving to: {output_path}")
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print("Done!")


if __name__ == "__main__":
    main()


