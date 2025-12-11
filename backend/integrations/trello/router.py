import logging
import json
from fastapi import APIRouter, HTTPException, Request, Response

from .models import TrelloWebhookPayload, TrelloWebhookResponse
from .publisher import TrelloEventPublisher

logger = logging.getLogger(__name__)


def get_trello_router(publisher: TrelloEventPublisher) -> APIRouter:
    router = APIRouter(prefix="/trello/webhook", tags=["trello"])

    @router.head("", status_code=200)
    @router.get("", status_code=200)
    async def verify_webhook() -> Response:
        """Handle Trello webhook verification (HEAD/GET should return 200)."""
        return Response(status_code=200)

    @router.post("", response_model=TrelloWebhookResponse)
    async def handle_webhook(request: Request):
        """Receive Trello webhook payloads and forward to publisher."""
        try:
            raw_payload = await request.json()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Invalid JSON in Trello webhook", exc_info=exc)
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        # Log the raw payload for debugging/shape inspection (no secrets expected in Trello payloads)
        logger.info(json.dumps({"event": "trello_webhook_raw", "payload": raw_payload}))

        try:
            payload = TrelloWebhookPayload.model_validate(raw_payload)
        except Exception as exc:
            logger.warning("Invalid Trello webhook payload", exc_info=exc, extra={"payload": raw_payload})
            raise HTTPException(status_code=400, detail="Invalid Trello webhook payload")

        log_record = {
            "event": "trello_webhook_received",
            "action_id": payload.action.id,
            "action_type": payload.action.type,
            "action_date": payload.action.date,
            "card_id": payload.action.data.card.id if payload.action.data.card else None,
            "card_name": payload.action.data.card.name if payload.action.data.card else None,
            "board_id": payload.action.data.board.id if payload.action.data.board else None,
            "board_name": payload.action.data.board.name if payload.action.data.board else None,
            "list_before_id": payload.action.data.list_before.id if payload.action.data.list_before else None,
            "list_before_name": payload.action.data.list_before.name if payload.action.data.list_before else None,
            "list_after_id": payload.action.data.list_after.id if payload.action.data.list_after else None,
            "list_after_name": payload.action.data.list_after.name if payload.action.data.list_after else None,
            "member_creator_id": payload.action.member_creator.id if payload.action.member_creator else None,
            "member_creator_username": payload.action.member_creator.username if payload.action.member_creator else None,
            "idempotency_key": payload.action.id,
        }
        logger.info(json.dumps(log_record))

        await publisher.publish(payload.action)

        return TrelloWebhookResponse(
            status="accepted",
            action_id=payload.action.id,
            action_type=payload.action.type,
            board_id=payload.action.data.board.id if payload.action.data.board else None,
            card_id=payload.action.data.card.id if payload.action.data.card else None,
        )

    return router
