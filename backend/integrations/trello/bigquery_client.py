"""
BigQuery client utilities for Trello webhook pipeline.

Handles all database operations:
- Event storage and idempotency checks
- Card and line item inserts/upserts
- Description change detection
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class TrelloBigQueryClient:
    """BigQuery client for Trello webhook pipeline operations."""

    def __init__(
        self,
        project_id: str,
        dataset_id: str = "trello_rag",
    ):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.client = bigquery.Client(project=project_id)

    def _table_ref(self, table_id: str) -> str:
        """Get full table reference."""
        return f"{self.project_id}.{self.dataset_id}.{table_id}"

    # =============================================================================
    # Event Operations
    # =============================================================================

    def event_exists(self, event_id: str) -> bool:
        """Check if event has already been processed (idempotency check)."""
        query = f"""
        SELECT event_id
        FROM `{self._table_ref('trello_webhook_events')}`
        WHERE event_id = @event_id
        LIMIT 1
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("event_id", "STRING", event_id),
            ]
        )
        result = self.client.query(query, job_config=job_config).result()
        return len(list(result)) > 0

    def insert_event(
        self,
        event_id: str,
        action_type: str,
        action_date: Optional[str],
        card_id: str,
        board_id: Optional[str] = None,
        board_name: Optional[str] = None,
        list_id: Optional[str] = None,
        list_name: Optional[str] = None,
        list_before_id: Optional[str] = None,
        list_before_name: Optional[str] = None,
        list_after_id: Optional[str] = None,
        list_after_name: Optional[str] = None,
        is_list_transition: Optional[bool] = None,
        member_creator_id: Optional[str] = None,
        member_creator_username: Optional[str] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert a webhook event into the events table."""
        now = datetime.now(timezone.utc).isoformat()
        
        row = {
            "event_id": event_id,
            "action_type": action_type,
            "action_date": action_date,
            "card_id": card_id,
            "board_id": board_id,
            "board_name": board_name,
            "list_id": list_id,
            "list_name": list_name,
            "list_before_id": list_before_id,
            "list_before_name": list_before_name,
            "list_after_id": list_after_id,
            "list_after_name": list_after_name,
            "is_list_transition": is_list_transition,
            "member_creator_id": member_creator_id,
            "member_creator_username": member_creator_username,
            "raw_payload": raw_payload,
            "processed": False,
            "processed_at": None,
            "extraction_triggered": None,
            "error_message": None,
            "created_at": now,
        }
        
        errors = self.client.insert_rows_json(
            self._table_ref("trello_webhook_events"),
            [row]
        )
        
        if errors:
            raise Exception(f"Failed to insert event: {errors}")
        
        logger.debug(f"Inserted event {event_id}")

    def mark_event_processed(
        self,
        event_id: str,
        extraction_triggered: bool = False,
        error_message: Optional[str] = None,
    ) -> None:
        """Mark an event as processed."""
        now = datetime.now(timezone.utc).isoformat()
        
        update_sql = f"""
        UPDATE `{self._table_ref('trello_webhook_events')}`
        SET 
            processed = @processed,
            processed_at = @processed_at,
            extraction_triggered = @extraction_triggered,
            error_message = @error_message
        WHERE event_id = @event_id
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("event_id", "STRING", event_id),
                bigquery.ScalarQueryParameter("processed", "BOOL", True),
                bigquery.ScalarQueryParameter("processed_at", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("extraction_triggered", "BOOL", extraction_triggered),
                bigquery.ScalarQueryParameter("error_message", "STRING", error_message),
            ]
        )
        
        self.client.query(update_sql, job_config=job_config).result()
        logger.debug(f"Marked event {event_id} as processed")

    def get_last_description(self, card_id: str) -> Optional[str]:
        """Get the last known description for a card from current table."""
        query = f"""
        SELECT `desc`
        FROM `{self._table_ref('bourquin_cards_current')}`
        WHERE card_id = @card_id
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("card_id", "STRING", card_id),
            ]
        )
        
        result = list(self.client.query(query, job_config=job_config).result())
        if result:
            return result[0].desc
        
        return None
    
    def get_current_card(self, card_id: str) -> Optional[Dict[str, Any]]:
        """Get current card from BigQuery (for preserving extracted fields on metadata updates)."""
        query = f"""
        SELECT *
        FROM `{self._table_ref('bourquin_cards_current')}`
        WHERE card_id = @card_id
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("card_id", "STRING", card_id),
            ]
        )
        
        result = list(self.client.query(query, job_config=job_config).result())
        if result:
            # Convert Row to dict
            row = result[0]
            return dict(row)
        return None
    
    def description_changed(self, card_id: str, new_description: Optional[str]) -> bool:
        """
        Check if card description has changed.
        
        Args:
            card_id: The card ID
            new_description: The new description from webhook/card data
            
        Returns:
            True if description changed, False if same or card doesn't exist
        """
        old_description = self.get_last_description(card_id)
        
        # If card doesn't exist, this is a new card (not a change)
        if old_description is None:
            return False
        
        # Normalize for comparison (strip whitespace, handle None)
        old_desc = (old_description or "").strip()
        new_desc = (new_description or "").strip()
        
        # Compare
        return old_desc != new_desc

    # =============================================================================
    # Card Operations
    # =============================================================================

    def card_exists_in_master(self, card_id: str) -> bool:
        """Check if card exists in master table."""
        query = f"""
        SELECT card_id
        FROM `{self._table_ref('bourquin_05122025_snapshot')}`
        WHERE card_id = @card_id
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("card_id", "STRING", card_id),
            ]
        )
        
        result = self.client.query(query, job_config=job_config).result()
        return len(list(result)) > 0

    def insert_card_master(
        self,
        card: Dict[str, Any],
        event_id: Optional[str] = None,
    ) -> None:
        """Insert card into master table (immutable, insert only)."""
        if self.card_exists_in_master(card["card_id"]):
            logger.info(f"Card {card['card_id']} already exists in master, skipping insert")
            return
        
        now = datetime.now(timezone.utc).isoformat()
        card_row = card.copy()
        card_row["first_extracted_at"] = now
        if event_id:
            card_row["first_extraction_event_id"] = event_id
        
        errors = self.client.insert_rows_json(
            self._table_ref("bourquin_05122025_snapshot"),
            [card_row]
        )
        
        if errors:
            raise Exception(f"Failed to insert card to master: {errors}")
        
        logger.info(f"Inserted card {card['card_id']} to master table")

    def upsert_card_current(
        self,
        card: Dict[str, Any],
        event_id: Optional[str] = None,
        extraction_triggered: bool = False,
    ) -> None:
        """Upsert card into current table (update if exists, insert if not)."""
        now = datetime.now(timezone.utc).isoformat()
        card_row = card.copy()
        card_row["last_updated_at"] = now
        if extraction_triggered:
            card_row["last_extracted_at"] = now
            if event_id:
                card_row["last_extraction_event_id"] = event_id
        
        # Check if card exists
        check_sql = f"""
        SELECT card_id
        FROM `{self._table_ref('bourquin_cards_current')}`
        WHERE card_id = @card_id
        LIMIT 1
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("card_id", "STRING", card_row["card_id"]),
            ]
        )
        
        result = list(self.client.query(check_sql, job_config=job_config).result())
        
        if result:
            # Update existing card
            # For simplicity, delete and re-insert (atomic operation)
            delete_sql = f"""
            DELETE FROM `{self._table_ref('bourquin_cards_current')}`
            WHERE card_id = @card_id
            """
            self.client.query(delete_sql, job_config=job_config).result()
        
        # Insert (whether new or updated)
        errors = self.client.insert_rows_json(
            self._table_ref("bourquin_cards_current"),
            [card_row]
        )
        
        if errors:
            raise Exception(f"Failed to upsert card to current: {errors}")
        
        logger.debug(f"Upserted card {card_row['card_id']} to current table")

    def _get_bq_type(self, value: Any) -> str:
        """Infer BigQuery type from Python value."""
        if value is None:
            return "STRING"  # Default, will be NULL
        if isinstance(value, bool):
            return "BOOL"
        if isinstance(value, int):
            return "INT64"
        if isinstance(value, float):
            return "FLOAT64"
        if isinstance(value, str):
            # Try to detect date/timestamp
            if "T" in value or ":" in value:
                return "TIMESTAMP"
            if "-" in value and len(value) == 10:
                return "DATE"
            return "STRING"
        return "STRING"

    # =============================================================================
    # Line Item Operations
    # =============================================================================

    def insert_line_items_master(
        self,
        card_id: str,
        line_items: List[Dict[str, Any]],
    ) -> None:
        """Insert line items into master table (immutable, insert only)."""
        if not line_items:
            return
        
        rows = []
        for item in line_items:
            row = item.copy()
            row["card_id"] = card_id
            rows.append(row)
        
        errors = self.client.insert_rows_json(
            self._table_ref("bourquin_05122025_snapshot_lineitems"),
            rows
        )
        
        if errors:
            raise Exception(f"Failed to insert line items to master: {errors}")
        
        logger.info(f"Inserted {len(rows)} line items for card {card_id} to master table")

    def upsert_line_items_current(
        self,
        card_id: str,
        line_items: List[Dict[str, Any]],
    ) -> None:
        """Upsert line items into current table (delete all, then insert new)."""
        # Delete existing line items for this card
        delete_sql = f"""
        DELETE FROM `{self._table_ref('bourquin_lineitems_current')}`
        WHERE card_id = @card_id
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("card_id", "STRING", card_id),
            ]
        )
        
        self.client.query(delete_sql, job_config=job_config).result()
        logger.debug(f"Deleted existing line items for card {card_id}")
        
        # Insert new line items
        if not line_items:
            logger.debug(f"No line items to insert for card {card_id}")
            return
        
        rows = []
        for item in line_items:
            row = item.copy()
            row["card_id"] = card_id
            rows.append(row)
        
        errors = self.client.insert_rows_json(
            self._table_ref("bourquin_lineitems_current"),
            rows
        )
        
        if errors:
            raise Exception(f"Failed to insert line items to current: {errors}")
        
        logger.info(f"Inserted {len(rows)} line items for card {card_id} to current table")
