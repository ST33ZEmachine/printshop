#!/usr/bin/env python3
"""
Create BigQuery tables for Trello webhook pipeline.

Creates:
1. trello_rag.trello_webhook_events - Event log
2. trello_rag.bourquin_cards_current - Current cards state
3. trello_rag.bourquin_lineitems_current - Current line items state

Usage:
    python setup_webhook_tables.py [--dataset DATASET] [--project PROJECT]
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from google.cloud import bigquery

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
DEFAULT_DATASET = "trello_rag"


def create_events_schema() -> List[bigquery.SchemaField]:
    """Create BigQuery schema for webhook events table."""
    return [
        bigquery.SchemaField("event_id", "STRING", mode="REQUIRED"),  # action.id (idempotency key)
        bigquery.SchemaField("action_type", "STRING"),  # "createCard", "updateCard", etc.
        bigquery.SchemaField("action_date", "TIMESTAMP"),  # When action occurred in Trello
        bigquery.SchemaField("card_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("board_id", "STRING"),
        bigquery.SchemaField("board_name", "STRING"),
        # List transition tracking
        bigquery.SchemaField("list_id", "STRING"),
        bigquery.SchemaField("list_name", "STRING"),
        bigquery.SchemaField("list_before_id", "STRING"),
        bigquery.SchemaField("list_before_name", "STRING"),
        bigquery.SchemaField("list_after_id", "STRING"),
        bigquery.SchemaField("list_after_name", "STRING"),
        bigquery.SchemaField("is_list_transition", "BOOLEAN"),
        # Metadata
        bigquery.SchemaField("member_creator_id", "STRING"),
        bigquery.SchemaField("member_creator_username", "STRING"),
        bigquery.SchemaField("raw_payload", "JSON"),  # Full webhook payload
        # Processing status
        bigquery.SchemaField("processed", "BOOLEAN"),
        bigquery.SchemaField("processed_at", "TIMESTAMP"),
        bigquery.SchemaField("extraction_triggered", "BOOLEAN"),  # Did this trigger LLM extraction?
        bigquery.SchemaField("error_message", "STRING"),
        bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),  # When we received webhook
    ]


def create_cards_current_schema() -> List[bigquery.SchemaField]:
    """
    Create BigQuery schema for current cards table.
    
    Base schema matches bourquin_05122025_snapshot, with additional fields:
    - Metadata fields (last_updated_at, last_extracted_at, etc.)
    - List/board tracking fields (list_id, list_name, board_id, board_name)
    
    Note: The snapshot table may not have list/board fields, but we need them
    for current state tracking.
    """
    # Base schema matches bourquin_05122025_snapshot
    base_schema = [
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
    
    # Add list/board tracking fields (needed for current state)
    tracking_fields = [
        bigquery.SchemaField("list_id", "STRING"),  # Current list ID
        bigquery.SchemaField("list_name", "STRING"),  # Current list name
        bigquery.SchemaField("board_id", "STRING"),  # Board ID
        bigquery.SchemaField("board_name", "STRING"),  # Board name
    ]
    
    # Add metadata fields for current table
    metadata_fields = [
        bigquery.SchemaField("last_updated_at", "TIMESTAMP"),  # When current record was last updated
        bigquery.SchemaField("last_extracted_at", "TIMESTAMP"),  # When LLM extraction last ran
        bigquery.SchemaField("last_extraction_event_id", "STRING"),  # Event that triggered last extraction
    ]
    
    return base_schema + tracking_fields + metadata_fields


def create_lineitems_current_schema() -> List[bigquery.SchemaField]:
    """Create BigQuery schema for current line items table (mirror of snapshot_lineitems)."""
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


def create_table(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    table_id: str,
    schema: List[bigquery.SchemaField],
    description: str = "",
    partition_field: str = None,
    cluster_fields: List[str] = None,
) -> None:
    """Create a BigQuery table with the given schema."""
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
    
    # Check if table exists
    try:
        existing_table = client.get_table(table_ref)
        logger.warning(f"Table {table_ref} already exists")
        logger.info(f"  Existing table has {existing_table.num_rows:,} rows")
        response = input(f"  Delete and recreate? (y/N): ")
        if response.lower() != 'y':
            logger.info(f"Skipping table {table_ref}")
            return
        client.delete_table(table_ref)
        logger.info(f"Deleted existing table {table_ref}")
    except Exception:
        pass  # Table doesn't exist, continue
    
    # Create table
    table = bigquery.Table(table_ref, schema=schema)
    table.description = description
    
    # Set partitioning
    if partition_field:
        table.time_partitioning = bigquery.TimePartitioning(
            field=partition_field,
            type_=bigquery.TimePartitioningType.DAY
        )
        logger.info(f"  Partitioning: {partition_field} (daily)")
    
    # Set clustering
    if cluster_fields:
        table.clustering_fields = cluster_fields
        logger.info(f"  Clustering: {', '.join(cluster_fields)}")
    
    table = client.create_table(table)
    logger.info(f"✅ Created table {table_ref}")
    logger.info(f"   Description: {description}")
    logger.info(f"   Schema: {len(schema)} fields")


def main():
    parser = argparse.ArgumentParser(
        description="Create BigQuery tables for Trello webhook pipeline"
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=DEFAULT_DATASET,
        help=f"BigQuery dataset ID (default: {DEFAULT_DATASET})"
    )
    parser.add_argument(
        "--project",
        type=str,
        default=PROJECT_ID,
        help=f"GCP project ID (default: from environment)"
    )
    
    args = parser.parse_args()
    
    # Validate environment
    project_id = args.project or PROJECT_ID
    if not project_id:
        logger.error("BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT environment variable not set.")
        logger.error("Or provide --project argument")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("TRELLO WEBHOOK TABLES SETUP")
    logger.info("=" * 60)
    logger.info(f"Project: {project_id}")
    logger.info(f"Dataset: {args.dataset}")
    logger.info("=" * 60)
    logger.info("")
    
    # Initialize BigQuery client
    client = bigquery.Client(project=project_id)
    
    # Create events table
    logger.info("Creating trello_webhook_events table...")
    create_table(
        client=client,
        project_id=project_id,
        dataset_id=args.dataset,
        table_id="trello_webhook_events",
        schema=create_events_schema(),
        description="Immutable log of all Trello webhook events. Tracks card changes, list transitions, and processing status.",
        partition_field="created_at",
        cluster_fields=["card_id", "action_type", "is_list_transition"]
    )
    logger.info("")
    
    # Create cards_current table
    logger.info("Creating bourquin_cards_current table...")
    create_table(
        client=client,
        project_id=project_id,
        dataset_id=args.dataset,
        table_id="bourquin_cards_current",
        schema=create_cards_current_schema(),
        description="Current state of all Trello cards. Updated on any card change. Mirrors bourquin_05122025_snapshot schema with additional metadata fields.",
    )
    logger.info("")
    
    # Create lineitems_current table
    logger.info("Creating bourquin_lineitems_current table...")
    create_table(
        client=client,
        project_id=project_id,
        dataset_id=args.dataset,
        table_id="bourquin_lineitems_current",
        schema=create_lineitems_current_schema(),
        description="Current state of all line items. Updated only when card description changes. Mirrors bourquin_05122025_snapshot_lineitems schema.",
    )
    logger.info("")
    
    logger.info("=" * 60)
    logger.info("SETUP COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Created tables in {project_id}.{args.dataset}:")
    logger.info("  - trello_webhook_events")
    logger.info("  - bourquin_cards_current")
    logger.info("  - bourquin_lineitems_current")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
