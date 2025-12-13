import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Protocol

from .models import TrelloAction
from .service import TrelloService

# Add project root to path for extraction service
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from .bigquery_client import TrelloBigQueryClient

# Import extraction service (from project root)
from extractionPipeline.extract_single_card import (
    CardExtractionService,
    format_card_for_bigquery,
    format_line_items_for_bigquery,
)

logger = logging.getLogger(__name__)


class TrelloEventPublisher(Protocol):
    async def publish(self, action: TrelloAction) -> None:
        """Publish a Trello action for downstream processing."""


class LoggingTrelloEventPublisher:
    """Basic publisher that logs webhook actions."""

    async def publish(self, action: TrelloAction) -> None:
        log_record = {
            "event": "trello_action_received",
            "action_id": action.id,
            "action_type": action.type,
            "action_date": action.date,
            "card_id": action.data.card.id if action.data.card else None,
            "card_name": action.data.card.name if action.data.card else None,
            "board_id": action.data.board.id if action.data.board else None,
            "board_name": action.data.board.name if action.data.board else None,
            "list_before_id": action.data.list_before.id if action.data.list_before else None,
            "list_before_name": action.data.list_before.name if action.data.list_before else None,
            "list_after_id": action.data.list_after.id if action.data.list_after else None,
            "list_after_name": action.data.list_after.name if action.data.list_after else None,
            "member_creator_id": action.member_creator.id if action.member_creator else None,
            "member_creator_username": action.member_creator.username if action.member_creator else None,
            "idempotency_key": action.id,
        }
        logger.info(json.dumps(log_record))


class BigQueryTrelloEventPublisher:
    """
    Publisher that stores webhook events in BigQuery and processes them.
    
    Handles:
    - Event storage and idempotency
    - Card creation (extract and insert)
    - Card updates (re-extract if description changed, update metadata otherwise)
    """

    def __init__(
        self,
        bq_client: TrelloBigQueryClient,
        trello_service: TrelloService,
        extraction_service: CardExtractionService,
    ):
        self.bq_client = bq_client
        self.trello_service = trello_service
        self.extraction_service = extraction_service

    async def publish(self, action: TrelloAction) -> None:
        """
        Publish a Trello action: store event and process asynchronously.
        
        This method returns immediately after storing the event.
        Processing happens in background.
        """
        # Check idempotency (run in executor)
        loop = asyncio.get_event_loop()
        exists = await loop.run_in_executor(
            None,
            lambda: self.bq_client.event_exists(action.id)
        )
        if exists:
            logger.info(f"Event {action.id} already processed, skipping")
            return

        # Store raw event (run in executor since it's synchronous)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._store_raw_event_sync(action))

        # Process event asynchronously (fire and forget)
        asyncio.create_task(self._process_event(action))

    def _store_raw_event_sync(self, action: TrelloAction) -> None:
        """Synchronous version of _store_raw_event for executor."""
        """Store raw webhook event in BigQuery."""
        # Determine if this is a list transition
        is_list_transition = (
            action.data.list_before is not None
            and action.data.list_after is not None
            and action.data.list_before.id != action.data.list_after.id
        )

        # Get current list (after transition, or from card/list data)
        list_id = None
        list_name = None
        if action.data.list_after:
            list_id = action.data.list_after.id
            list_name = action.data.list_after.name
        elif action.data.list:
            list_id = action.data.list.id
            list_name = action.data.list.name
        elif action.data.card:
            list_id = action.data.card.id_list

        self.bq_client.insert_event(
            event_id=action.id,
            action_type=action.type,
            action_date=action.date,
            card_id=action.data.card.id if action.data.card else "",
            board_id=action.data.board.id if action.data.board else None,
            board_name=action.data.board.name if action.data.board else None,
            list_id=list_id,
            list_name=list_name,
            list_before_id=action.data.list_before.id if action.data.list_before else None,
            list_before_name=action.data.list_before.name if action.data.list_before else None,
            list_after_id=action.data.list_after.id if action.data.list_after else None,
            list_after_name=action.data.list_after.name if action.data.list_after else None,
            is_list_transition=is_list_transition,
            member_creator_id=action.member_creator.id if action.member_creator else None,
            member_creator_username=action.member_creator.username if action.member_creator else None,
            raw_payload=action.model_dump(),
        )
        logger.debug(f"Stored event {action.id}")

    async def _process_event(self, action: TrelloAction) -> None:
        """
        Process a webhook event: extract data and update BigQuery tables.
        
        Handles:
        - createCard: Extract and insert into master + current tables
        - updateCard: Check if description changed, re-extract if needed
        """
        try:
            # Only process card-related actions
            if not action.data.card or not action.data.card.id:
                logger.debug(f"Event {action.id} has no card, skipping processing")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self.bq_client.mark_event_processed(action.id, extraction_triggered=False)
                )
                return

            card_id = action.data.card.id
            action_type = action.type

            logger.info(f"Processing event {action.id}: {action_type} for card {card_id}")

            # Route to appropriate handler
            if action_type == "createCard":
                await self._handle_create_card(action)
            elif action_type == "updateCard":
                await self._handle_update_card(action)
            elif action_type == "deleteCard":
                await self._handle_delete_card(action)
            else:
                # Other action types - just mark as processed
                logger.debug(f"Event {action.id} is {action_type}, no processing needed")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: self.bq_client.mark_event_processed(action.id, extraction_triggered=False)
                )

        except Exception as e:
            logger.error(f"Error processing event {action.id}: {e}", exc_info=True)
            # Mark event as processed with error (run in executor)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.bq_client.mark_event_processed(
                    action.id,
                    extraction_triggered=False,
                    error_message=str(e),
                )
            )

    async def _handle_create_card(self, action: TrelloAction) -> None:
        """Handle createCard webhook: extract and insert into master + current tables."""
        card_id = action.data.card.id

        # Check if card already exists (idempotency) - run in executor
        loop = asyncio.get_event_loop()
        exists = await loop.run_in_executor(
            None,
            lambda: self.bq_client.card_exists_in_master(card_id)
        )
        if exists:
            logger.info(f"Card {card_id} already exists in master, skipping")
            await loop.run_in_executor(
                None,
                lambda: self.bq_client.mark_event_processed(action.id, extraction_triggered=False)
            )
            return

        # Fetch full card data from Trello API (run in executor to avoid blocking)
        logger.debug(f"Fetching full card data for {card_id}")
        loop = asyncio.get_event_loop()
        card_data = await loop.run_in_executor(
            None,
            lambda: self.trello_service.fetch_card(card_id)
        )

        # Extract with LLM (synchronous call in async context)
        logger.info(f"Extracting card {card_id} with LLM...")
        # Run extraction in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        extracted = await loop.run_in_executor(
            None,
            lambda: self.extraction_service.extract_single_card(card_data, enrich=True)
        )

        # Get board/list info from action
        board_id = action.data.board.id if action.data.board else None
        board_name = action.data.board.name if action.data.board else None
        list_id = action.data.list_after.id if action.data.list_after else action.data.list.id if action.data.list else None
        list_name = action.data.list_after.name if action.data.list_after else action.data.list.name if action.data.list else None

        # Format for BigQuery
        card_row = format_card_for_bigquery(
            extracted,
            board_id=board_id,
            board_name=board_name,
            list_id=list_id,
            list_name=list_name,
        )

        # Insert into master table (run in executor)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: self.bq_client.insert_card_master(card_row, event_id=action.id)
        )

        # Insert into current table
        await loop.run_in_executor(
            None,
            lambda: self.bq_client.upsert_card_current(
                card_row,
                event_id=action.id,
                extraction_triggered=True,
                event_type="createCard",
            )
        )

        # Insert line items
        line_items = extracted.get("line_items", [])
        if line_items:
            line_item_rows = format_line_items_for_bigquery(card_id, line_items)
            await loop.run_in_executor(
                None,
                lambda: self.bq_client.insert_line_items_master(card_id, line_item_rows)
            )
            await loop.run_in_executor(
                None,
                lambda: self.bq_client.upsert_line_items_current(card_id, line_item_rows)
            )

            logger.info(f"Successfully processed createCard for {card_id}")
            # Mark event as processed (run in executor)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.bq_client.mark_event_processed(action.id, extraction_triggered=True)
            )

    async def _handle_update_card(self, action: TrelloAction) -> None:
        """Handle updateCard webhook: extract first, then do single MERGE operation."""
        card_id = action.data.card.id

        # Fetch full card data from Trello API (run in executor to avoid blocking)
        logger.debug(f"Fetching full card data for {card_id}")
        loop = asyncio.get_event_loop()
        card_data = await loop.run_in_executor(
            None,
            lambda: self.trello_service.fetch_card(card_id)
        )

        # Get current card to detect what changed
        current_card = await loop.run_in_executor(
            None,
            lambda: self.bq_client.get_current_card(card_id)
        )
        
        # Detect what changed to set appropriate event type
        new_description = card_data.get("desc")
        description_changed = (
            current_card is None or 
            current_card.get("desc") != new_description
        ) if new_description else False
        
        # Check if card was archived/unarchived
        new_closed = card_data.get("closed", False)
        was_archived = current_card and current_card.get("closed") != new_closed and new_closed
        was_unarchived = current_card and current_card.get("closed") != new_closed and not new_closed
        
        # Check if list changed
        new_list_id = card_data.get("idList")
        list_changed = current_card and current_card.get("list_id") != new_list_id
        
        # Check if title changed
        new_name = card_data.get("name")
        title_changed = current_card and current_card.get("name") != new_name
        
        # Determine event type
        if was_archived:
            event_type = "updateCard:archived"
        elif was_unarchived:
            event_type = "updateCard:unarchived"
        elif description_changed:
            event_type = "updateCard:desc_changed"
        elif list_changed:
            event_type = "updateCard:list_moved"
        elif title_changed:
            event_type = "updateCard:title_changed"
        else:
            event_type = "updateCard:other"

        # Extract immediately (before any BigQuery operations)
        logger.info(f"Extracting card {card_id} with LLM...")
        extracted = await loop.run_in_executor(
            None,
            lambda: self.extraction_service.extract_single_card(card_data, enrich=True)
        )

        # Get board/list info from action
        board_id = action.data.board.id if action.data.board else None
        board_name = action.data.board.name if action.data.board else None
        
        # Get list info (prefer list_after for transitions, else current list)
        list_id = None
        list_name = None
        if action.data.list_after:
            list_id = action.data.list_after.id
            list_name = action.data.list_after.name
        elif action.data.list:
            list_id = action.data.list.id
            list_name = action.data.list.name
        else:
            # Get from card data (idList is in card, but name might not be)
            list_id = card_data.get("idList")
            # Try to get list name from current card if available
            if list_id and not list_name and current_card:
                list_name = current_card.get("list_name")

        # Format for BigQuery
        card_row = format_card_for_bigquery(
            extracted,
            board_id=board_id,
            board_name=board_name,
            list_id=list_id,
            list_name=list_name,
        )

        # Single MERGE operation (works with streaming buffer, handles both insert and update)
        await loop.run_in_executor(
            None,
            lambda: self.bq_client.upsert_card_current(
                card_row,
                event_id=action.id,
                extraction_triggered=description_changed,
                event_type=event_type,
            )
        )

        # Update line items only if description changed
        if description_changed:
            line_items = extracted.get("line_items", [])
            if line_items:
                line_item_rows = format_line_items_for_bigquery(card_id, line_items)
                await loop.run_in_executor(
                    None,
                    lambda: self.bq_client.upsert_line_items_current(card_id, line_item_rows)
                )
            logger.info(f"Description changed - updated line items for card {card_id}")
        else:
            logger.debug(f"Description unchanged for card {card_id}, line items not updated")

        logger.info(f"Successfully processed updateCard for {card_id} (event_type: {event_type})")
        # Mark event as processed (run in executor)
        await loop.run_in_executor(
            None,
            lambda: self.bq_client.mark_event_processed(action.id, extraction_triggered=description_changed)
        )

    async def _handle_delete_card(self, action: TrelloAction) -> None:
        """Handle deleteCard webhook: mark card as deleted in current table."""
        card_id = action.data.card.id
        
        # Get current card from BigQuery (can't fetch from Trello API since it's deleted)
        loop = asyncio.get_event_loop()
        current_card = await loop.run_in_executor(
            None,
            lambda: self.bq_client.get_current_card(card_id)
        )
        
        if not current_card:
            logger.warning(f"Card {card_id} not found in current table, cannot mark as deleted")
            await loop.run_in_executor(
                None,
                lambda: self.bq_client.mark_event_processed(action.id, extraction_triggered=False)
            )
            return
        
        # Update card to mark as deleted (closed=true, event_type=deleteCard)
        # Keep all other fields the same
        card_row = current_card.copy()
        card_row["closed"] = True
        card_row["last_updated_at"] = datetime.now(timezone.utc).isoformat()
        
        # Use MERGE to update the card with deleteCard event type
        await loop.run_in_executor(
            None,
            lambda: self.bq_client.upsert_card_current(
                card_row,
                event_id=action.id,
                extraction_triggered=False,
                event_type="deleteCard",
            )
        )
        
        logger.info(f"Successfully processed deleteCard for {card_id}")
        # Mark event as processed (run in executor)
        await loop.run_in_executor(
            None,
            lambda: self.bq_client.mark_event_processed(action.id, extraction_triggered=False)
        )

