"""
BigQuery client utilities for Trello webhook pipeline.

Handles all database operations:
- Event storage and idempotency checks
- Card and line item inserts/upserts
- Description change detection
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from google.cloud import bigquery
from google.api_core.exceptions import BadRequest

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
        
        # Convert raw_payload dict to JSON string for BigQuery JSON type
        raw_payload_json = json.dumps(raw_payload) if raw_payload else None
        
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
            "raw_payload": raw_payload_json,
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
        """
        Mark an event as processed using MERGE.
        
        Note: This may fail if the event was recently inserted (streaming buffer).
        The event is still logged, so this is non-critical. We catch and log the error.
        """
        now = datetime.now(timezone.utc).isoformat()
        
        try:
            # Use MERGE instead of UPDATE to work with streaming buffer
            # Note: MERGE with UPDATE still counts as UPDATE, so may fail on streaming buffer rows
            merge_sql = f"""
            MERGE `{self._table_ref('trello_webhook_events')}` AS target
            USING (
                SELECT 
                    @event_id AS event_id,
                    @processed AS processed,
                    @processed_at AS processed_at,
                    @extraction_triggered AS extraction_triggered,
                    @error_message AS error_message
            ) AS source
            ON target.event_id = source.event_id
            WHEN MATCHED THEN UPDATE SET
                processed = source.processed,
                processed_at = source.processed_at,
                extraction_triggered = source.extraction_triggered,
                error_message = source.error_message
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
            
            self.client.query(merge_sql, job_config=job_config).result()
            logger.debug(f"Marked event {event_id} as processed")
        except Exception as e:
            # Streaming buffer issue - event is still logged, so this is non-critical
            # We'll retry marking as processed later if needed, or just query by event_id
            if "streaming buffer" in str(e).lower():
                logger.debug(f"Could not mark event {event_id} as processed (streaming buffer): {e}. Event is still logged.")
            else:
                logger.warning(f"Error marking event {event_id} as processed: {e}")

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
        
        # Remove fields that don't exist in master table schema
        # Master table doesn't have last_updated_at, last_extracted_at, last_extraction_event_id, last_event_type
        card_row.pop("last_updated_at", None)
        card_row.pop("last_extracted_at", None)
        card_row.pop("last_extraction_event_id", None)
        card_row.pop("last_event_type", None)
        
        # Add extraction tracking fields (for debugging and data lineage)
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

    def _enqueue_retry(
        self,
        operation_type: str,
        target_table: str,
        payload: Dict[str, Any],
        retry_count: int = 0,
    ) -> str:
        """
        Enqueue a failed operation to the retry queue for later processing.
        
        Returns the update_id for tracking.
        """
        import uuid
        from datetime import timedelta
        
        update_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        
        # Calculate next retry time with exponential backoff
        # Initial: 5 minutes, then 10, 20, 40 minutes
        delay_minutes = 5 * (2 ** retry_count)
        next_retry_at = now + timedelta(minutes=delay_minutes)
        
        row = {
            "update_id": update_id,
            "operation_type": operation_type,
            "target_table": target_table,
            "payload": json.dumps(payload),  # Store as JSON string
            "retry_count": retry_count,
            "first_queued_at": now.isoformat(),
            "last_retry_at": None,
            "next_retry_at": next_retry_at.isoformat(),
            "status": "pending",
            "error_message": None,
            "completed_at": None,
            "created_at": now.isoformat(),
        }
        
        errors = self.client.insert_rows_json(
            self._table_ref("pending_bigquery_updates"),
            [row]
        )
        
        if errors:
            logger.error(f"Failed to enqueue retry operation: {errors}")
            raise Exception(f"Failed to enqueue retry: {errors}")
        
        logger.info(
            f"Enqueued {operation_type} for {target_table} (update_id: {update_id}, "
            f"retry_count: {retry_count}, next_retry: {next_retry_at.isoformat()})"
        )
        return update_id

    def _retry_merge_with_backoff(
        self,
        merge_func: Callable[[], None],
        operation_name: str,
        operation_type: str,
        target_table: str,
        payload: Dict[str, Any],
        max_retries: int = 2,  # Reduced - we'll enqueue after this
        initial_delay: float = 2.0,
    ) -> None:
        """
        Retry a MERGE operation with exponential backoff, then enqueue if it still fails.
        
        BigQuery streaming buffer prevents UPDATE operations on recently inserted rows
        (typically for a few minutes). This retries with increasing delays, then enqueues
        for background processing if all retries fail.
        """
        delay = initial_delay
        last_error = None
        
        for attempt in range(max_retries):
            try:
                merge_func()
                if attempt > 0:
                    logger.info(f"{operation_name} succeeded on retry {attempt}")
                return
            except BadRequest as e:
                error_msg = str(e).lower()
                if "streaming buffer" in error_msg:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"{operation_name} failed due to streaming buffer (attempt {attempt + 1}/{max_retries}). "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                        delay *= 2  # Exponential backoff
                    else:
                        # All retries failed - enqueue for background processing
                        logger.warning(
                            f"{operation_name} failed after {max_retries} attempts due to streaming buffer. "
                            f"Enqueuing for background retry..."
                        )
                        try:
                            self._enqueue_retry(
                                operation_type=operation_type,
                                target_table=target_table,
                                payload=payload,
                                retry_count=0,
                            )
                            logger.info(f"Successfully enqueued {operation_name} for background retry")
                            return  # Don't raise - operation is queued
                        except Exception as enqueue_error:
                            logger.error(
                                f"Failed to enqueue {operation_name} after streaming buffer failure: {enqueue_error}. "
                                f"Original error: {e}"
                            )
                            raise  # Re-raise original error if enqueue fails
                else:
                    # Not a streaming buffer error, re-raise immediately
                    raise
            except Exception as e:
                # Other errors, re-raise immediately
                raise
        
        # Should not reach here, but just in case
        if last_error:
            raise last_error

    def upsert_card_current(
        self,
        card: Dict[str, Any],
        event_id: Optional[str] = None,
        extraction_triggered: bool = False,
        event_type: Optional[str] = None,
    ) -> None:
        """Upsert card into current table using MERGE (update if exists, insert if not)."""
        now = datetime.now(timezone.utc).isoformat()
        card_row = card.copy()
        card_row["last_updated_at"] = now
        if extraction_triggered:
            card_row["last_extracted_at"] = now
            if event_id:
                card_row["last_extraction_event_id"] = event_id
        if event_type:
            card_row["last_event_type"] = event_type
        
        # Build MERGE statement - single atomic operation that works with streaming buffer
        # MERGE handles both INSERT and UPDATE in one operation
        merge_sql = f"""
        MERGE `{self._table_ref('bourquin_cards_current')}` AS target
        USING (
            SELECT 
                @card_id AS card_id,
                @name AS name,
                @desc AS `desc`,
                @labels AS labels,
                @closed AS closed,
                @dateLastActivity AS dateLastActivity,
                @purchaser AS purchaser,
                @order_summary AS order_summary,
                @primary_buyer_name AS primary_buyer_name,
                @primary_buyer_email AS primary_buyer_email,
                @date_created AS date_created,
                @datetime_created AS datetime_created,
                @year_created AS year_created,
                @month_created AS month_created,
                @year_month AS year_month,
                @unix_timestamp AS unix_timestamp,
                @line_item_count AS line_item_count,
                @list_id AS list_id,
                @list_name AS list_name,
                @board_id AS board_id,
                @board_name AS board_name,
                @last_updated_at AS last_updated_at,
                @last_extracted_at AS last_extracted_at,
                @last_extraction_event_id AS last_extraction_event_id,
                @last_event_type AS last_event_type
        ) AS source
        ON target.card_id = source.card_id
        WHEN MATCHED THEN UPDATE SET
            name = source.name,
            `desc` = source.`desc`,
            labels = source.labels,
            closed = source.closed,
            dateLastActivity = source.dateLastActivity,
            purchaser = source.purchaser,
            order_summary = source.order_summary,
            primary_buyer_name = source.primary_buyer_name,
            primary_buyer_email = source.primary_buyer_email,
            date_created = source.date_created,
            datetime_created = source.datetime_created,
            year_created = source.year_created,
            month_created = source.month_created,
            year_month = source.year_month,
            unix_timestamp = source.unix_timestamp,
            line_item_count = source.line_item_count,
            list_id = source.list_id,
            list_name = source.list_name,
            board_id = source.board_id,
            board_name = source.board_name,
            last_updated_at = source.last_updated_at,
            last_extracted_at = source.last_extracted_at,
            last_extraction_event_id = source.last_extraction_event_id,
            last_event_type = source.last_event_type
        WHEN NOT MATCHED THEN INSERT (
            card_id, name, `desc`, labels, closed, dateLastActivity,
            purchaser, order_summary, primary_buyer_name, primary_buyer_email,
            date_created, datetime_created, year_created, month_created, year_month,
            unix_timestamp, line_item_count, list_id, list_name, board_id, board_name,
            last_updated_at, last_extracted_at, last_extraction_event_id, last_event_type
        ) VALUES (
            source.card_id, source.name, source.`desc`, source.labels, source.closed, source.dateLastActivity,
            source.purchaser, source.order_summary, source.primary_buyer_name, source.primary_buyer_email,
            source.date_created, source.datetime_created, source.year_created, source.month_created, source.year_month,
            source.unix_timestamp, source.line_item_count, source.list_id, source.list_name, source.board_id, source.board_name,
            source.last_updated_at, source.last_extracted_at, source.last_extraction_event_id, source.last_event_type
        )
        """
        
        # Build query parameters
        params = [
            bigquery.ScalarQueryParameter("card_id", "STRING", card_row.get("card_id")),
            bigquery.ScalarQueryParameter("name", "STRING", card_row.get("name")),
            bigquery.ScalarQueryParameter("desc", "STRING", card_row.get("desc")),
            bigquery.ScalarQueryParameter("labels", "STRING", card_row.get("labels")),
            bigquery.ScalarQueryParameter("closed", "BOOL", card_row.get("closed", False)),
            bigquery.ScalarQueryParameter("dateLastActivity", "TIMESTAMP", card_row.get("dateLastActivity")),
            bigquery.ScalarQueryParameter("purchaser", "STRING", card_row.get("purchaser")),
            bigquery.ScalarQueryParameter("order_summary", "STRING", card_row.get("order_summary")),
            bigquery.ScalarQueryParameter("primary_buyer_name", "STRING", card_row.get("primary_buyer_name")),
            bigquery.ScalarQueryParameter("primary_buyer_email", "STRING", card_row.get("primary_buyer_email")),
            bigquery.ScalarQueryParameter("date_created", "DATE", card_row.get("date_created")),
            bigquery.ScalarQueryParameter("datetime_created", "TIMESTAMP", card_row.get("datetime_created")),
            bigquery.ScalarQueryParameter("year_created", "INT64", card_row.get("year_created")),
            bigquery.ScalarQueryParameter("month_created", "INT64", card_row.get("month_created")),
            bigquery.ScalarQueryParameter("year_month", "STRING", card_row.get("year_month")),
            bigquery.ScalarQueryParameter("unix_timestamp", "INT64", card_row.get("unix_timestamp")),
            bigquery.ScalarQueryParameter("line_item_count", "INT64", card_row.get("line_item_count", 0)),
            bigquery.ScalarQueryParameter("list_id", "STRING", card_row.get("list_id")),
            bigquery.ScalarQueryParameter("list_name", "STRING", card_row.get("list_name")),
            bigquery.ScalarQueryParameter("board_id", "STRING", card_row.get("board_id")),
            bigquery.ScalarQueryParameter("board_name", "STRING", card_row.get("board_name")),
            bigquery.ScalarQueryParameter("last_updated_at", "TIMESTAMP", card_row.get("last_updated_at")),
            bigquery.ScalarQueryParameter("last_extracted_at", "TIMESTAMP", card_row.get("last_extracted_at")),
            bigquery.ScalarQueryParameter("last_extraction_event_id", "STRING", card_row.get("last_extraction_event_id")),
            bigquery.ScalarQueryParameter("last_event_type", "STRING", card_row.get("last_event_type")),
        ]
        
        job_config = bigquery.QueryJobConfig(query_parameters=params)
        
        # Retry MERGE operation if it fails due to streaming buffer, then enqueue if needed
        def execute_merge():
            self.client.query(merge_sql, job_config=job_config).result()
        
        # Prepare payload for retry queue (if needed)
        # Store card_row data - we'll reconstruct the MERGE query when processing
        payload = {
            "card_row": card_row,
            "event_id": event_id,
            "extraction_triggered": extraction_triggered,
            "event_type": event_type,
        }
        
        self._retry_merge_with_backoff(
            execute_merge,
            f"MERGE card {card_row['card_id']} to current table",
            operation_type="upsert_card",
            target_table="bourquin_cards_current",
            payload=payload,
            max_retries=2,
            initial_delay=2.0,
        )
        
        logger.debug(f"Merged card {card_row['card_id']} to current table")

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
        # Delete existing line items for this card (with retry for streaming buffer)
        delete_sql = f"""
        DELETE FROM `{self._table_ref('bourquin_lineitems_current')}`
        WHERE card_id = @card_id
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("card_id", "STRING", card_id),
            ]
        )
        
        def execute_delete():
            self.client.query(delete_sql, job_config=job_config).result()
        
        # Prepare payload for retry queue (if DELETE fails)
        payload = {
            "card_id": card_id,
            "line_items": line_items,
            "delete_sql": delete_sql,
        }
        
        try:
            self._retry_merge_with_backoff(
                execute_delete,
                f"DELETE line items for card {card_id}",
                operation_type="upsert_line_items",
                target_table="bourquin_lineitems_current",
                payload=payload,
                max_retries=2,
                initial_delay=2.0,
            )
            logger.debug(f"Deleted existing line items for card {card_id}")
        except Exception as e:
            # If DELETE fails and wasn't enqueued, re-raise
            # (enqueue happens inside _retry_merge_with_backoff, so if we get here, enqueue failed)
            logger.error(f"Failed to delete line items for card {card_id} and enqueue failed: {e}")
            raise
        
        # Insert new line items (INSERT doesn't have streaming buffer issues)
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

    # =============================================================================
    # Queue Processing (for streaming buffer retries)
    # =============================================================================

    def process_retry_queue(self, max_items: int = 50, max_retries: int = 5) -> Dict[str, Any]:
        """
        Process pending BigQuery operations from the retry queue.
        
        Returns:
            Dict with counts of processed, succeeded, failed, and skipped items.
        """
        now = datetime.now(timezone.utc)
        
        # Query for pending items ready to retry
        query = f"""
        SELECT 
            update_id,
            operation_type,
            target_table,
            payload,
            retry_count,
            first_queued_at,
            next_retry_at
        FROM `{self._table_ref('pending_bigquery_updates')}`
        WHERE status = 'pending'
          AND next_retry_at <= @now
        ORDER BY first_queued_at ASC
        LIMIT @max_items
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("now", "TIMESTAMP", now.isoformat()),
                bigquery.ScalarQueryParameter("max_items", "INT64", max_items),
            ]
        )
        
        results = list(self.client.query(query, job_config=job_config).result())
        
        if not results:
            logger.info("No pending items in retry queue")
            return {
                "processed": 0,
                "succeeded": 0,
                "failed": 0,
                "skipped": 0,
            }
        
        logger.info(f"Processing {len(results)} items from retry queue")
        
        stats = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
        }
        
        for row in results:
            update_id = row.update_id
            operation_type = row.operation_type
            target_table = row.target_table
            payload = json.loads(row.payload) if isinstance(row.payload, str) else row.payload
            retry_count = row.retry_count
            
            # Mark as processing
            self._update_queue_item_status(update_id, "processing", last_retry_at=now.isoformat())
            
            try:
                # Reconstruct and execute the operation
                if operation_type == "upsert_card":
                    self._retry_upsert_card(payload)
                elif operation_type == "upsert_line_items":
                    self._retry_upsert_line_items(payload)
                else:
                    logger.warning(f"Unknown operation_type: {operation_type} for update_id: {update_id}")
                    self._update_queue_item_status(update_id, "failed", error_message=f"Unknown operation_type: {operation_type}")
                    stats["skipped"] += 1
                    continue
                
                # Success - mark as completed
                self._update_queue_item_status(update_id, "completed", completed_at=now.isoformat())
                stats["succeeded"] += 1
                logger.info(f"Successfully processed {operation_type} for update_id: {update_id}")
                
            except BadRequest as e:
                error_msg = str(e).lower()
                if "streaming buffer" in error_msg:
                    # Still in streaming buffer - reschedule
                    if retry_count >= max_retries:
                        logger.error(
                            f"Max retries ({max_retries}) reached for update_id: {update_id}. "
                            f"Marking as failed."
                        )
                        self._update_queue_item_status(
                            update_id,
                            "failed",
                            error_message=f"Max retries exceeded: {str(e)}",
                        )
                        stats["failed"] += 1
                    else:
                        # Reschedule with exponential backoff
                        from datetime import timedelta
                        delay_minutes = 5 * (2 ** (retry_count + 1))
                        next_retry = now + timedelta(minutes=delay_minutes)
                        self._reschedule_queue_item(
                            update_id,
                            retry_count + 1,
                            next_retry.isoformat(),
                            error_message=str(e),
                        )
                        logger.warning(
                            f"Still in streaming buffer for update_id: {update_id}. "
                            f"Rescheduled for {next_retry.isoformat()} (retry {retry_count + 1}/{max_retries})"
                        )
                        stats["failed"] += 1  # Failed this attempt, but will retry
                else:
                    # Other BigQuery error - mark as failed
                    logger.error(f"BigQuery error for update_id: {update_id}: {e}")
                    self._update_queue_item_status(update_id, "failed", error_message=str(e))
                    stats["failed"] += 1
                    
            except Exception as e:
                # Unexpected error - mark as failed
                logger.error(f"Unexpected error processing update_id: {update_id}: {e}", exc_info=True)
                self._update_queue_item_status(update_id, "failed", error_message=str(e))
                stats["failed"] += 1
            
            stats["processed"] += 1
        
        logger.info(
            f"Queue processing complete: {stats['succeeded']} succeeded, "
            f"{stats['failed']} failed, {stats['skipped']} skipped"
        )
        return stats

    def _retry_upsert_card(self, payload: Dict[str, Any]) -> None:
        """Reconstruct and retry a card upsert operation."""
        card_row = payload["card_row"]
        event_id = payload.get("event_id")
        extraction_triggered = payload.get("extraction_triggered", False)
        event_type = payload.get("event_type")
        
        # Call the upsert method directly (it will handle retries)
        self.upsert_card_current(
            card_row,
            event_id=event_id,
            extraction_triggered=extraction_triggered,
            event_type=event_type,
        )

    def _retry_upsert_line_items(self, payload: Dict[str, Any]) -> None:
        """Reconstruct and retry a line items upsert operation."""
        card_id = payload["card_id"]
        line_items = payload["line_items"]
        
        # Call the upsert method directly
        self.upsert_line_items_current(card_id, line_items)

    def _update_queue_item_status(
        self,
        update_id: str,
        status: str,
        error_message: Optional[str] = None,
        completed_at: Optional[str] = None,
        last_retry_at: Optional[str] = None,
    ) -> None:
        """Update the status of a queue item."""
        now = datetime.now(timezone.utc).isoformat()
        
        update_sql = f"""
        UPDATE `{self._table_ref('pending_bigquery_updates')}`
        SET 
            status = @status,
            error_message = @error_message,
            completed_at = @completed_at,
            last_retry_at = @last_retry_at
        WHERE update_id = @update_id
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("update_id", "STRING", update_id),
                bigquery.ScalarQueryParameter("status", "STRING", status),
                bigquery.ScalarQueryParameter("error_message", "STRING", error_message),
                bigquery.ScalarQueryParameter("completed_at", "TIMESTAMP", completed_at),
                bigquery.ScalarQueryParameter("last_retry_at", "TIMESTAMP", last_retry_at),
            ]
        )
        
        self.client.query(update_sql, job_config=job_config).result()

    def _reschedule_queue_item(
        self,
        update_id: str,
        retry_count: int,
        next_retry_at: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Reschedule a queue item for later retry."""
        now = datetime.now(timezone.utc).isoformat()
        
        update_sql = f"""
        UPDATE `{self._table_ref('pending_bigquery_updates')}`
        SET 
            status = 'pending',
            retry_count = @retry_count,
            next_retry_at = @next_retry_at,
            last_retry_at = @last_retry_at,
            error_message = @error_message
        WHERE update_id = @update_id
        """
        
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("update_id", "STRING", update_id),
                bigquery.ScalarQueryParameter("retry_count", "INT64", retry_count),
                bigquery.ScalarQueryParameter("next_retry_at", "TIMESTAMP", next_retry_at),
                bigquery.ScalarQueryParameter("last_retry_at", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("error_message", "STRING", error_message),
            ]
        )
        
        self.client.query(update_sql, job_config=job_config).result()
