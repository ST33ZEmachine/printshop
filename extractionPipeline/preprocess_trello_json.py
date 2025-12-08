#!/usr/bin/env python3
"""
Preprocess Trello JSON to Lightweight JSONL

Converts large Trello JSON exports to a lightweight JSONL format
that can be streamed without loading everything into memory.

Usage:
    python preprocess_trello_json.py --input LyB2G53h.json --output LyB2G53h_cards.jsonl
"""

import argparse
import json
from pathlib import Path


def preprocess(input_path: Path, output_path: Path):
    """Convert Trello JSON to lightweight JSONL."""
    print(f"Loading: {input_path}")
    print(f"File size: {input_path.stat().st_size / 1024 / 1024:.1f} MB")
    
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    cards = data.get('cards', [])
    print(f"Found {len(cards):,} cards")
    
    # Extract board metadata
    board_info = {
        'board_id': data.get('id', ''),
        'board_name': data.get('name', ''),
        'total_cards': len(cards)
    }
    
    # Write lightweight JSONL - one card per line with only essential fields
    print(f"Writing: {output_path}")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        # First line is board metadata
        f.write(json.dumps({'_type': 'board_info', **board_info}) + '\n')
        
        # Then each card
        for card in cards:
            lightweight = {
                '_type': 'card',
                'id': card.get('id', ''),
                'name': card.get('name', ''),
                'desc': card.get('desc', ''),
                'labels': [l.get('name', '') for l in card.get('labels', [])],
                'closed': card.get('closed', False),
                'dateLastActivity': card.get('dateLastActivity', ''),
            }
            f.write(json.dumps(lightweight, ensure_ascii=False) + '\n')
    
    output_size = output_path.stat().st_size / 1024 / 1024
    print(f"Output size: {output_size:.1f} MB")
    print(f"Size reduction: {(1 - output_size / (input_path.stat().st_size / 1024 / 1024)) * 100:.1f}%")
    print(f"Done! Output: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Preprocess Trello JSON to JSONL")
    parser.add_argument("--input", "-i", required=True, help="Input Trello JSON file")
    parser.add_argument("--output", "-o", help="Output JSONL file (default: input_cards.jsonl)")
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        return
    
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = input_path.parent / f"{input_path.stem}_cards.jsonl"
    
    preprocess(input_path, output_path)


if __name__ == "__main__":
    main()


