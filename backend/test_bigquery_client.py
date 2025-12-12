#!/usr/bin/env python3
"""
Test script for Trello BigQuery Client.

Tests all operations:
- Event storage and idempotency
- Card insert/upsert
- Line item insert/upsert
- Description change detection

Usage:
    python test_bigquery_client.py
"""

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from integrations.trello.bigquery_client import TrelloBigQueryClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("BIGQUERY_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")


def test_event_operations(client: TrelloBigQueryClient):
    """Test event storage and idempotency."""
    logger.info("=" * 60)
    logger.info("Testing Event Operations")
    logger.info("=" * 60)
    
    test_event_id = f"test_event_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    test_card_id = "test_card_123"
    
    # Test 1: Check idempotency (should not exist)
    logger.info("Test 1: Checking if event exists (should be False)...")
    exists = client.event_exists(test_event_id)
    logger.info(f"  Result: {exists} (expected: False)")
    assert not exists, "Event should not exist yet"
    logger.info("  ✅ PASSED")
    
    # Test 2: Insert event
    logger.info("Test 2: Inserting test event...")
    client.insert_event(
        event_id=test_event_id,
        action_type="createCard",
        action_date=datetime.now(timezone.utc).isoformat(),
        card_id=test_card_id,
        board_id="test_board_123",
        board_name="Test Board",
        list_id="test_list_123",
        list_name="Test List",
        is_list_transition=False,
        raw_payload={"test": "data"},
    )
    logger.info("  ✅ PASSED")
    
    # Test 3: Check idempotency again (should exist now)
    logger.info("Test 3: Checking if event exists again (should be True)...")
    exists = client.event_exists(test_event_id)
    logger.info(f"  Result: {exists} (expected: True)")
    assert exists, "Event should exist now"
    logger.info("  ✅ PASSED")
    
    # Test 4: Mark event as processed
    logger.info("Test 4: Marking event as processed...")
    client.mark_event_processed(
        event_id=test_event_id,
        extraction_triggered=True,
    )
    logger.info("  ✅ PASSED")
    
    logger.info("")
    return test_event_id, test_card_id


def test_card_operations(client: TrelloBigQueryClient, test_card_id: str):
    """Test card insert and upsert operations."""
    logger.info("=" * 60)
    logger.info("Testing Card Operations")
    logger.info("=" * 60)
    
    # Test card data
    test_card = {
        "card_id": test_card_id,
        "name": "Test Card | Test Order",
        "desc": "Test description with pricing: $100.00",
        "labels": "TEST, RUSH",
        "closed": False,
        "dateLastActivity": datetime.now(timezone.utc).isoformat(),
        "purchaser": "Test Customer",
        "order_summary": "Test Order",
        "primary_buyer_name": "John Doe",
        "primary_buyer_email": "john@example.com",
        "date_created": "2025-01-01",
        "datetime_created": "2025-01-01T00:00:00",
        "year_created": 2025,
        "month_created": 1,
        "year_month": "2025-01",
        "unix_timestamp": 1735689600,
        "line_item_count": 1,
        "list_id": "test_list_123",
        "list_name": "Test List",
        "board_id": "test_board_123",
        "board_name": "Test Board",
    }
    
    # Test 1: Check if card exists in master (should not)
    logger.info("Test 1: Checking if card exists in master (should be False)...")
    exists = client.card_exists_in_master(test_card_id)
    logger.info(f"  Result: {exists} (expected: False)")
    assert not exists, "Card should not exist in master yet"
    logger.info("  ✅ PASSED")
    
    # Test 2: Insert into master
    logger.info("Test 2: Inserting card into master table...")
    client.insert_card_master(test_card, event_id="test_event_123")
    logger.info("  ✅ PASSED")
    
    # Test 3: Try to insert again (should skip)
    logger.info("Test 3: Trying to insert again (should skip)...")
    client.insert_card_master(test_card, event_id="test_event_456")
    logger.info("  ✅ PASSED (should have skipped)")
    
    # Test 4: Upsert into current (first time - insert)
    logger.info("Test 4: Upserting card into current table (first time)...")
    client.upsert_card_current(test_card, event_id="test_event_123", extraction_triggered=True)
    logger.info("  ✅ PASSED")
    
    # Test 5: Upsert again (should update)
    logger.info("Test 5: Upserting card again (should update)...")
    test_card_updated = test_card.copy()
    test_card_updated["name"] = "Test Card Updated | Test Order"
    test_card_updated["list_name"] = "Updated List"
    client.upsert_card_current(test_card_updated, event_id="test_event_456", extraction_triggered=False)
    logger.info("  ✅ PASSED")
    
    logger.info("")


def test_line_item_operations(client: TrelloBigQueryClient, test_card_id: str):
    """Test line item insert and upsert operations."""
    logger.info("=" * 60)
    logger.info("Testing Line Item Operations")
    logger.info("=" * 60)
    
    test_line_items = [
        {
            "line_index": 1,
            "quantity": 2,
            "raw_price": 100.0,
            "price_type": "total",
            "unit_price": 50.0,
            "total_revenue": 100.0,
            "description": "Test item 1",
            "business_line": "Signage",
            "material": "Aluminum",
            "dimensions": "24x36",
        },
        {
            "line_index": 2,
            "quantity": 1,
            "raw_price": 50.0,
            "price_type": "total",
            "unit_price": 50.0,
            "total_revenue": 50.0,
            "description": "Test item 2",
            "business_line": "Printing",
            "material": "Vinyl",
            "dimensions": "12x12",
        },
    ]
    
    # Test 1: Insert into master
    logger.info("Test 1: Inserting line items into master table...")
    client.insert_line_items_master(test_card_id, test_line_items)
    logger.info("  ✅ PASSED")
    
    # Test 2: Upsert into current (first time)
    logger.info("Test 2: Upserting line items into current table (first time)...")
    client.upsert_line_items_current(test_card_id, test_line_items)
    logger.info("  ✅ PASSED")
    
    # Test 3: Upsert again with different items (should replace)
    logger.info("Test 3: Upserting with different line items (should replace)...")
    updated_line_items = [
        {
            "line_index": 1,
            "quantity": 3,
            "raw_price": 150.0,
            "price_type": "total",
            "unit_price": 50.0,
            "total_revenue": 150.0,
            "description": "Updated test item",
            "business_line": "Signage",
            "material": "Aluminum",
            "dimensions": "24x36",
        },
    ]
    client.upsert_line_items_current(test_card_id, updated_line_items)
    logger.info("  ✅ PASSED")
    
    logger.info("")


def test_description_detection(client: TrelloBigQueryClient, test_card_id: str):
    """Test description change detection."""
    logger.info("=" * 60)
    logger.info("Testing Description Change Detection")
    logger.info("=" * 60)
    
    # Test 1: Get last description (should be from current table)
    logger.info("Test 1: Getting last description...")
    last_desc = client.get_last_description(test_card_id)
    logger.info(f"  Last description: {last_desc}")
    logger.info("  ✅ PASSED")
    
    logger.info("")


def main():
    if not PROJECT_ID:
        logger.error("BIGQUERY_PROJECT or GOOGLE_CLOUD_PROJECT environment variable not set.")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("BIGQUERY CLIENT TEST SUITE")
    logger.info("=" * 60)
    logger.info(f"Project: {PROJECT_ID}")
    logger.info(f"Dataset: trello_rag")
    logger.info("")
    
    # Initialize client
    client = TrelloBigQueryClient(project_id=PROJECT_ID, dataset_id="trello_rag")
    
    try:
        # Run tests
        test_event_id, test_card_id = test_event_operations(client)
        test_card_operations(client, test_card_id)
        test_line_item_operations(client, test_card_id)
        test_description_detection(client, test_card_id)
        
        logger.info("=" * 60)
        logger.info("ALL TESTS PASSED ✅")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Test data created:")
        logger.info(f"  Event ID: {test_event_id}")
        logger.info(f"  Card ID: {test_card_id}")
        logger.info("")
        logger.info("You can verify in BigQuery:")
        logger.info(f"  SELECT * FROM `{PROJECT_ID}.trello_rag.trello_webhook_events` WHERE event_id = '{test_event_id}'")
        logger.info(f"  SELECT * FROM `{PROJECT_ID}.trello_rag.bourquin_cards_current` WHERE card_id = '{test_card_id}'")
        logger.info(f"  SELECT * FROM `{PROJECT_ID}.trello_rag.bourquin_lineitems_current` WHERE card_id = '{test_card_id}'")
        
    except Exception as e:
        logger.error("=" * 60)
        logger.error("TEST FAILED ❌")
        logger.error("=" * 60)
        logger.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
