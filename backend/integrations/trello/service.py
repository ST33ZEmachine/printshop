import logging
from typing import List, Optional

import httpx

from .config import TrelloSettings, TrelloWebhookMeta

logger = logging.getLogger(__name__)

TRELLO_API_BASE = "https://api.trello.com/1"


class TrelloService:
    """
    Helper for Trello API interactions (non-destructive, read-only).
    
    All board data operations are READ-ONLY:
    - get_board(): Reads board information
    - fetch_card(): Reads card data
    
    No card, list, or board data is ever modified.
    Only webhook infrastructure (subscriptions) can be created/deleted.
    """

    def __init__(
        self,
        settings: TrelloSettings,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.settings = settings
        self.client = client or httpx.Client(base_url=TRELLO_API_BASE, timeout=30.0)

    def _auth_params(self) -> dict[str, str]:
        return {
            "key": self.settings.trello_key,
            "token": self.settings.trello_token,
        }

    def register_webhook(
        self,
        id_model: str,
        callback_url: str,
        description: str | None = None,
    ) -> TrelloWebhookMeta:
        """Register a webhook for the given model (board)."""
        payload = {
            "idModel": id_model,
            "callbackURL": callback_url,
            "description": description or "maxPrint Trello webhook",
            "active": True,
        }
        response = self.client.post("/webhooks", params=self._auth_params(), data=payload)
        response.raise_for_status()
        data = response.json()
        return TrelloWebhookMeta.model_validate(data)

    def list_webhooks(self) -> List[TrelloWebhookMeta]:
        """List webhooks for the current token."""
        response = self.client.get(f"/tokens/{self.settings.trello_token}/webhooks", params=self._auth_params())
        response.raise_for_status()
        return [TrelloWebhookMeta.model_validate(item) for item in response.json()]

    def delete_webhook(self, webhook_id: str) -> None:
        """Delete a webhook by id (cleanup only)."""
        response = self.client.delete(f"/webhooks/{webhook_id}", params=self._auth_params())
        response.raise_for_status()
        logger.info("Deleted Trello webhook", extra={"webhook_id": webhook_id})

    def get_board(self, board_id: str) -> dict:
        """
        Get board information - useful for testing access.
        
        READ-ONLY operation - does not modify any Trello data.
        """
        response = self.client.get(f"/boards/{board_id}", params=self._auth_params())
        response.raise_for_status()
        return response.json()

    def fetch_card(self, card_id: str) -> dict:
        """
        Fetch full card data including description, attachments, comments.
        Used by webhook pipeline to get complete card data.
        
        READ-ONLY operation - does not modify any Trello data.
        """
        response = self.client.get(
            f"/cards/{card_id}",
            params={
                **self._auth_params(),
                "fields": "all",
                "attachments": "true",
                "actions": "commentCard",
            }
        )
        response.raise_for_status()
        return response.json()

    def list_boards(self) -> List[dict]:
        """
        List all boards accessible with the current API key/token.
        
        READ-ONLY operation - does not modify any Trello data.
        """
        response = self.client.get(
            "/members/me/boards",
            params={
                **self._auth_params(),
                "fields": "id,name,url,closed,idOrganization",
            }
        )
        response.raise_for_status()
        return response.json()

