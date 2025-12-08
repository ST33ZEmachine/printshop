#!/usr/bin/env python3
"""
Upload Enriched Trello Data to BigQuery

Flattens the enriched Trello JSON into two tables:
- bourquin_05122025_snapshot (cards)
- bourquin_05122025_snapshot_lineitems (line items)

Usage:
    python upload_to_bigquery.py --input LyB2G53h_cards_extracted.json [--dataset DATASET]
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from google.cloud import bigquery

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
DEFAULT_DATASET = "trello_rag"
CARDS_TABLE = "bourquin_05122025_snapshot"
LINEITEMS_TABLE = "bourquin_05122025_snapshot_lineitems"


def create_cards_schema() -> List[bigquery.SchemaField]:
    """Create BigQuery schema for cards table."""
    return [
        bigquery.SchemaField("card_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("desc", "STRING"),
        bigquery.SchemaField("labels", "STRING"),  # Comma-separated
        bigquery.SchemaField("closed", "BOOLEAN"),
        bigquery.SchemaField("dateLastActivity", "TIMESTAMP"),
        # Enriched fields - title parsing
        bigquery.SchemaField("purchaser", "STRING"),
        bigquery.SchemaField("order_summary", "STRING"),
        # Enriched fields - buyer extraction
        bigquery.SchemaField("primary_buyer_name", "STRING"),
        bigquery.SchemaField("primary_buyer_email", "STRING"),
        # Date fields
        bigquery.SchemaField("date_created", "DATE"),
        bigquery.SchemaField("datetime_created", "TIMESTAMP"),
        bigquery.SchemaField("year_created", "INTEGER"),
        bigquery.SchemaField("month_created", "INTEGER"),
        bigquery.SchemaField("year_month", "STRING"),
        bigquery.SchemaField("unix_timestamp", "INTEGER"),
        # Summary
        bigquery.SchemaField("line_item_count", "INTEGER"),
    ]


def create_lineitems_schema() -> List[bigquery.SchemaField]:
    """Create BigQuery schema for line items table."""
    return [
        bigquery.SchemaField("card_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("line_index", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("quantity", "INTEGER"),
        bigquery.SchemaField("raw_price", "FLOAT"),
        bigquery.SchemaField("price_type", "STRING"),  # "per_unit" or "total"
        bigquery.SchemaField("unit_price", "FLOAT"),
        bigquery.SchemaField("total_revenue", "FLOAT"),
        bigquery.SchemaField("description", "STRING"),
        # Enrichment fields
        bigquery.SchemaField("business_line", "STRING"),  # "Signage", "Printing", "Engraving"
        bigquery.SchemaField("material", "STRING"),
        bigquery.SchemaField("dimensions", "STRING"),
    ]


def flatten_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a card for BigQuery upload."""
    # Process labels
    label_names = []
    for lbl in card.get("labels", []):
        if isinstance(lbl, dict):
            name = (lbl.get("name") or "").strip()
        elif isinstance(lbl, str):
            name = lbl.strip()
        else:
            name = str(lbl).strip()
        if name:
            label_names.append(name)
    labels_str = ", ".join(label_names) if label_names else None
    
    # Parse dateLastActivity - keep as ISO string for BigQuery
    date_last_activity = card.get("dateLastActivity")
    
    # Parse datetime_created - keep as ISO string for BigQuery
    datetime_created = card.get("datetime_created")
    
    # Parse date_created - keep as YYYY-MM-DD string for BigQuery
    date_created = card.get("date_created")
    
    return {
        "card_id": card.get("id"),
        "name": card.get("name"),
        "desc": card.get("desc"),
        "labels": labels_str,
        "closed": card.get("closed"),
        "dateLastActivity": date_last_activity,  # ISO string
        "purchaser": card.get("purchaser"),
        "order_summary": card.get("order_summary"),
        "primary_buyer_name": card.get("primary_buyer_name"),
        "primary_buyer_email": card.get("primary_buyer_email"),
        "date_created": date_created,  # YYYY-MM-DD string
        "datetime_created": datetime_created,  # ISO string
        "year_created": card.get("year_created"),
        "month_created": card.get("month_created"),
        "year_month": card.get("year_month"),
        "unix_timestamp": card.get("unix_timestamp"),
        "line_item_count": card.get("line_item_count", 0),
    }


def flatten_line_items(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten all line items from all cards."""
    line_items = []
    for card in cards:
        card_id = card.get("id")
        for item in card.get("line_items", []):
            line_items.append({
                "card_id": card_id,
                "line_index": item.get("line_index"),
                "quantity": item.get("quantity"),
                "raw_price": item.get("raw_price"),
                "price_type": item.get("price_type"),
                "unit_price": item.get("unit_price"),
                "total_revenue": item.get("total_revenue"),
                "description": item.get("description"),
                "business_line": item.get("business_line"),
                "material": item.get("material"),
                "dimensions": item.get("dimensions"),
            })
    return line_items


def upload_table(
    rows: List[Dict[str, Any]],
    project_id: str,
    dataset_id: str,
    table_id: str,
    schema: List[bigquery.SchemaField],
    replace: bool = True
) -> None:
    """Upload rows to BigQuery table."""
    client = bigquery.Client(project=project_id)
    
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    
    # Create dataset if it doesn't exist
    dataset_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")
    dataset_ref.location = "US"
    try:
        client.get_dataset(dataset_ref)
        logger.info(f"Dataset {dataset_id} exists")
    except Exception:
        client.create_dataset(dataset_ref)
        logger.info(f"Created dataset {dataset_id}")
    
    # Delete existing table if replacing
    if replace:
        try:
            client.delete_table(table_ref)
            logger.info(f"Deleted existing table {table_ref}")
        except Exception:
            pass
    
    # Create table with schema
    table = bigquery.Table(table_ref, schema=schema)
    table = client.create_table(table, exists_ok=True)
    logger.info(f"Table {table_ref} ready")
    
    # Insert rows in chunks
    logger.info(f"Uploading {len(rows)} rows to {table_ref}...")
    
    chunk_size = 10000
    total_errors = []
    
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        errors = client.insert_rows_json(table_ref, chunk)
        if errors:
            total_errors.extend(errors)
            logger.error(f"Errors in chunk {i//chunk_size + 1}: {errors[:5]}")
        else:
            logger.info(f"Uploaded chunk {i//chunk_size + 1} ({len(chunk)} rows)")
    
    if total_errors:
        logger.error(f"Total errors: {len(total_errors)}")
        raise Exception(f"Upload failed with {len(total_errors)} errors")
    else:
        logger.info(f"Successfully uploaded all {len(rows)} rows")


def main():
    parser = argparse.ArgumentParser(
        description="Upload enriched Trello data to BigQuery"
    )
    parser.add_argument(
        "--input",
        type=str,
        required=True,
        help="Input enriched JSON file path"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=DEFAULT_DATASET,
        help=f"BigQuery dataset ID (default: {DEFAULT_DATASET})"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing tables instead of replacing"
    )
    
    args = parser.parse_args()
    
    # Validate environment
    if not PROJECT_ID:
        logger.error("BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT environment variable not set.")
        sys.exit(1)
    
    # Load input file
    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("BIGQUERY UPLOAD")
    logger.info("=" * 60)
    logger.info(f"Input: {input_path}")
    logger.info(f"Project: {PROJECT_ID}")
    logger.info(f"Dataset: {args.dataset}")
    logger.info(f"Cards table: {CARDS_TABLE}")
    logger.info(f"Line items table: {LINEITEMS_TABLE}")
    logger.info(f"Mode: {'Append' if args.append else 'Replace'}")
    logger.info("=" * 60)
    
    logger.info(f"Loading {input_path}...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    cards = data.get("cards", [])
    logger.info(f"Found {len(cards):,} cards")
    
    # Flatten cards
    logger.info("Flattening cards...")
    card_rows = []
    for card in cards:
        try:
            row = flatten_card(card)
            card_rows.append(row)
        except Exception as e:
            logger.warning(f"Failed to flatten card {card.get('id')}: {e}")
    
    logger.info(f"Prepared {len(card_rows):,} card rows")
    
    # Flatten line items
    logger.info("Flattening line items...")
    line_item_rows = flatten_line_items(cards)
    logger.info(f"Prepared {len(line_item_rows):,} line item rows")
    
    # Upload cards table
    logger.info("")
    logger.info("Uploading cards table...")
    upload_table(
        card_rows,
        PROJECT_ID,
        args.dataset,
        CARDS_TABLE,
        create_cards_schema(),
        replace=not args.append
    )
    
    # Upload line items table
    logger.info("")
    logger.info("Uploading line items table...")
    upload_table(
        line_item_rows,
        PROJECT_ID,
        args.dataset,
        LINEITEMS_TABLE,
        create_lineitems_schema(),
        replace=not args.append
    )
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("UPLOAD COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Cards table: {PROJECT_ID}.{args.dataset}.{CARDS_TABLE}")
    logger.info(f"  Rows: {len(card_rows):,}")
    logger.info(f"Line items table: {PROJECT_ID}.{args.dataset}.{LINEITEMS_TABLE}")
    logger.info(f"  Rows: {len(line_item_rows):,}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
