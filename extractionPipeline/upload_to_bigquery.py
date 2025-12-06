"""
Upload Enriched Trello Data to BigQuery

This script flattens the enriched Trello JSON and uploads it to BigQuery.

Usage:
    python upload_to_bigquery.py --input ENRICHED_JSON [--dataset DATASET] [--table TABLE]
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
DEFAULT_TABLE = "trello_cards_enriched"


def flatten_card(card: Dict[str, Any], lists_by_id: Dict[str, str], board_id: str, board_name: str) -> Dict[str, Any]:
    """
    Flatten a single card into a BigQuery-compatible row.
    
    Args:
        card: Card dictionary with enriched fields
        lists_by_id: Mapping of list ID to list name
        board_id: Board ID
        board_name: Board name
        
    Returns:
        Flattened dictionary ready for BigQuery
    """
    list_id = card.get("idList")
    list_name = lists_by_id.get(list_id, "")
    
    # Card labels: array of objects with "name"
    label_names = []
    for lbl in card.get("labels", []):
        name = (lbl.get("name") or "").strip()
        if name:
            label_names.append(name)
    labels_str = ", ".join(label_names)
    
    # Extract buyer names/emails as comma-separated strings
    buyer_names = card.get("buyer_names", [])
    buyer_emails = card.get("buyer_emails", [])
    
    return {
        "card_id": card.get("id"),
        "board_id": board_id,
        "board_name": board_name,
        "list_id": list_id,
        "list_name": list_name,
        "name": card.get("name"),
        "desc": card.get("desc"),
        "labels": labels_str,
        "closed": card.get("closed"),
        "due": card.get("due"),
        "dateLastActivity": card.get("dateLastActivity"),
        "shortUrl": card.get("shortUrl"),
        # New enriched fields - title parsing
        "purchaser": card.get("purchaser"),
        "order_summary": card.get("order_summary"),
        # New enriched fields - LLM extraction
        "buyer_names": ", ".join(buyer_names) if buyer_names else None,
        "buyer_emails": ", ".join(buyer_emails) if buyer_emails else None,
        "primary_buyer_name": card.get("primary_buyer_name"),
        "primary_buyer_email": card.get("primary_buyer_email"),
        "buyer_confidence": card.get("buyer_confidence"),
    }


def create_table_schema() -> List[bigquery.SchemaField]:
    """Create BigQuery table schema."""
    return [
        bigquery.SchemaField("card_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("board_id", "STRING"),
        bigquery.SchemaField("board_name", "STRING"),
        bigquery.SchemaField("list_id", "STRING"),
        bigquery.SchemaField("list_name", "STRING"),
        bigquery.SchemaField("name", "STRING"),
        bigquery.SchemaField("desc", "STRING"),
        bigquery.SchemaField("labels", "STRING"),
        bigquery.SchemaField("closed", "BOOLEAN"),
        bigquery.SchemaField("due", "TIMESTAMP"),
        bigquery.SchemaField("dateLastActivity", "TIMESTAMP"),
        bigquery.SchemaField("shortUrl", "STRING"),
        # Enriched fields - title parsing
        bigquery.SchemaField("purchaser", "STRING"),
        bigquery.SchemaField("order_summary", "STRING"),
        # Enriched fields - LLM extraction
        bigquery.SchemaField("buyer_names", "STRING"),
        bigquery.SchemaField("buyer_emails", "STRING"),
        bigquery.SchemaField("primary_buyer_name", "STRING"),
        bigquery.SchemaField("primary_buyer_email", "STRING"),
        bigquery.SchemaField("buyer_confidence", "STRING"),
    ]


def upload_to_bigquery(
    rows: List[Dict[str, Any]],
    project_id: str,
    dataset_id: str,
    table_id: str,
    replace: bool = True
) -> None:
    """
    Upload rows to BigQuery table.
    
    Args:
        rows: List of flattened card dictionaries
        project_id: GCP project ID
        dataset_id: BigQuery dataset ID
        table_id: BigQuery table ID
        replace: If True, replace table; if False, append
    """
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
    
    # Create table with schema
    schema = create_table_schema()
    table = bigquery.Table(table_ref, schema=schema)
    
    if replace:
        # Delete existing table if it exists
        try:
            client.delete_table(table_ref)
            logger.info(f"Deleted existing table {table_ref}")
        except Exception:
            pass
    
    # Create table
    table = client.create_table(table, exists_ok=True)
    logger.info(f"Table {table_ref} ready")
    
    # Insert rows
    logger.info(f"Uploading {len(rows)} rows to {table_ref}...")
    
    # BigQuery insert in chunks of 10000
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
        "--table",
        type=str,
        default=DEFAULT_TABLE,
        help=f"BigQuery table ID (default: {DEFAULT_TABLE})"
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing table instead of replacing"
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
    
    logger.info(f"Loading {input_path}...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Get board info
    board_id = data.get("id", "")
    board_name = data.get("name", "")
    
    # Map list_id -> list_name
    lists_by_id = {
        lst["id"]: lst.get("name", "")
        for lst in data.get("lists", [])
    }
    
    # Flatten cards
    cards = data.get("cards", [])
    logger.info(f"Flattening {len(cards)} cards...")
    
    rows = []
    for card in cards:
        try:
            row = flatten_card(card, lists_by_id, board_id, board_name)
            rows.append(row)
        except Exception as e:
            logger.warning(f"Failed to flatten card {card.get('id')}: {e}")
    
    logger.info(f"Prepared {len(rows)} rows for upload")
    
    # Upload to BigQuery
    logger.info(f"Project: {PROJECT_ID}")
    logger.info(f"Dataset: {args.dataset}")
    logger.info(f"Table: {args.table}")
    logger.info(f"Mode: {'Append' if args.append else 'Replace'}")
    
    upload_to_bigquery(
        rows,
        PROJECT_ID,
        args.dataset,
        args.table,
        replace=not args.append
    )
    
    logger.info("="*60)
    logger.info("UPLOAD COMPLETE")
    logger.info("="*60)
    logger.info(f"Table: {PROJECT_ID}.{args.dataset}.{args.table}")
    logger.info(f"Rows uploaded: {len(rows)}")
    logger.info("="*60)


if __name__ == "__main__":
    main()

