import json
import logging
from typing import Protocol

from .models import TrelloAction

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

