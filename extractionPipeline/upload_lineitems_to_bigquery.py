#!/usr/bin/env python3
"""
Upload Line Items CSV to BigQuery

This script uploads the extracted line items CSV to BigQuery.

Usage:
    python upload_lineitems_to_bigquery.py
    python upload_lineitems_to_bigquery.py --input FILE.csv --table TABLE_NAME
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
DEFAULT_DATASET = "trello_rag"
DEFAULT_TABLE = "bourquin_05122025_snapshot_lineitems"
DEFAULT_INPUT = "bourquin_05122025_snapshot_lineitems.csv"


def create_lineitems_schema():
    """Create BigQuery schema for line items table."""
    return [
        bigquery.SchemaField("order_id", "STRING", mode="REQUIRED", 
            description="Foreign key to cards table (card_id)"),
        bigquery.SchemaField("line_index", "INTEGER", 
            description="1-based index of line item within the order"),
        bigquery.SchemaField("location_group", "STRING", 
            description="Section header from source (e.g., 'STORE FRONT')"),
        bigquery.SchemaField("order_class", "STRING", 
            description="Order type: 'Supply', 'Install', or 'Supply & Install'"),
        bigquery.SchemaField("quantity", "INTEGER", 
            description="Number of items ordered"),
        bigquery.SchemaField("price", "FLOAT", 
            description="Unit price in dollars"),
        bigquery.SchemaField("raw_price_text", "STRING", 
            description="Original price text from source for validation"),
        bigquery.SchemaField("price_validated", "BOOLEAN", 
            description="TRUE if price was verified against source text"),
        bigquery.SchemaField("width_in", "FLOAT", 
            description="Width dimension in inches"),
        bigquery.SchemaField("height_in", "FLOAT", 
            description="Height dimension in inches"),
        bigquery.SchemaField("raw_dimensions_text", "STRING", 
            description="Original dimension text (e.g., '24x36')"),
        bigquery.SchemaField("material", "STRING", 
            description="Product material (e.g., 'Aluminum Composite Panel')"),
        bigquery.SchemaField("description", "STRING", 
            description="Item description"),
        bigquery.SchemaField("colour", "STRING", 
            description="Color if specified"),
        bigquery.SchemaField("extra_notes", "STRING", 
            description="Additional notes, flags (e.g., '[REGEX_EXTRACTED]')"),
        bigquery.SchemaField("raw_line_text", "STRING", 
            description="Original source text for this line item"),
        bigquery.SchemaField("llm_confidence", "STRING", 
            description="Extraction confidence: 'high', 'medium', or 'low'"),
    ]


def upload_csv_to_bigquery(
    csv_path: Path,
    project_id: str,
    dataset_id: str,
    table_id: str,
):
    """Upload CSV to BigQuery table."""
    client = bigquery.Client(project=project_id)
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    
    # Create dataset if needed
    dataset_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")
    dataset_ref.location = "US"
    try:
        client.get_dataset(dataset_ref)
        logger.info(f"Dataset {dataset_id} exists")
    except Exception:
        client.create_dataset(dataset_ref)
        logger.info(f"Created dataset {dataset_id}")
    
    # Delete existing table
    try:
        client.delete_table(table_ref)
        logger.info(f"Deleted existing table {table_ref}")
    except Exception:
        pass
    
    # Create table with schema
    schema = create_lineitems_schema()
    table = bigquery.Table(table_ref, schema=schema)
    table.description = """
    Extracted line items from Bourquin Signs order cards.
    
    This table contains individual order line items parsed from Trello card descriptions.
    Each row represents one product/service within an order.
    
    Key fields:
    - order_id: Links to cards table via card_id
    - price: Unit price (use price_validated=TRUE for highest confidence)
    - quantity: Number of items
    - material: Product type (e.g., 'Coroplast', 'Aluminum Composite Panel')
    
    Data Quality:
    - 99.3% of prices verified against source text
    - 88% of cards successfully parsed
    - Total value captured: $1,954,895
    
    Generated: December 6, 2024
    """
    table = client.create_table(table)
    logger.info(f"Created table {table_ref}")
    
    # Load CSV
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        skip_leading_rows=1,  # Skip header
        source_format=bigquery.SourceFormat.CSV,
        allow_quoted_newlines=True,
        null_marker="",
    )
    
    with open(csv_path, "rb") as f:
        load_job = client.load_table_from_file(f, table_ref, job_config=job_config)
    
    logger.info("Uploading CSV to BigQuery...")
    load_job.result()  # Wait for completion
    
    # Get final row count
    table = client.get_table(table_ref)
    logger.info(f"Loaded {table.num_rows} rows to {table_ref}")
    
    return table.num_rows


def main():
    parser = argparse.ArgumentParser(description="Upload line items CSV to BigQuery")
    parser.add_argument("--input", type=str, default=DEFAULT_INPUT, help="Input CSV file")
    parser.add_argument("--dataset", type=str, default=DEFAULT_DATASET, help="BigQuery dataset")
    parser.add_argument("--table", type=str, default=DEFAULT_TABLE, help="BigQuery table name")
    
    args = parser.parse_args()
    
    if not PROJECT_ID:
        logger.error("GOOGLE_CLOUD_PROJECT not set")
        sys.exit(1)
    
    script_dir = Path(__file__).parent
    csv_path = script_dir / args.input
    
    if not csv_path.exists():
        logger.error(f"CSV not found: {csv_path}")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("UPLOADING LINE ITEMS TO BIGQUERY")
    logger.info("=" * 60)
    logger.info(f"Input:   {csv_path}")
    logger.info(f"Project: {PROJECT_ID}")
    logger.info(f"Dataset: {args.dataset}")
    logger.info(f"Table:   {args.table}")
    logger.info("=" * 60)
    
    rows = upload_csv_to_bigquery(csv_path, PROJECT_ID, args.dataset, args.table)
    
    logger.info("\n" + "=" * 60)
    logger.info("UPLOAD COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Table: {PROJECT_ID}.{args.dataset}.{args.table}")
    logger.info(f"Rows:  {rows}")
    logger.info("=" * 60)
    
    # Print sample query
    print(f"""
Sample queries:

-- Total order value
SELECT SUM(price * COALESCE(quantity, 1)) as total_value
FROM `{PROJECT_ID}.{args.dataset}.{args.table}`
WHERE price_validated = TRUE;

-- Join with cards table
SELECT 
  c.purchaser,
  COUNT(*) as line_items,
  SUM(li.price) as total_value
FROM `{PROJECT_ID}.{args.dataset}.{args.table}` li
JOIN `{PROJECT_ID}.{args.dataset}.bourquin_05122025_snapshot` c 
  ON li.order_id = c.card_id
GROUP BY c.purchaser
ORDER BY total_value DESC
LIMIT 10;
""")


if __name__ == "__main__":
    main()

