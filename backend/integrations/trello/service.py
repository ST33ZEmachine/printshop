import logging
from typing import List, Optional

import httpx

from .config import TrelloSettings, TrelloWebhookMeta

logger = logging.getLogger(__name__)

TRELLO_API_BASE = "https://api.trello.com/1"


class TrelloService:
    """Helper for Trello API interactions (non-destructive)."""

    def __init__(
        self,
        settings: TrelloSettings,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.settings = settings
        self.client = client or httpx.Client(base_url=TRELLO_API_BASE, timeout=10.0)

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

