#!/usr/bin/env python3
"""
Register webhook for Bourquin Signs board.

This will set up webhook notifications for the production board.
"""

import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).parent))

from integrations.trello.config import TrelloSettings
from integrations.trello.service import TrelloService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Bourquin board ID (from test_trello_access.py output)
BOURQUIN_BOARD_ID = "64df710946c4c9a25a0f9bd5"


def main():
    try:
        settings = TrelloSettings()
        if not settings.webhook_callback_url:
            logger.error("TRELLO_WEBHOOK_CALLBACK_URL environment variable not set")
            logger.error("Set this to your public webhook endpoint URL")
            logger.error("Example: https://your-service.run.app/trello/webhook")
            return 1
        
        service = TrelloService(settings)
        
        logger.info("=" * 60)
        logger.info("Registering Webhook for Bourquin Signs Board")
        logger.info("=" * 60)
        logger.info(f"Board ID: {BOURQUIN_BOARD_ID}")
        logger.info(f"Callback URL: {settings.webhook_callback_url}")
        logger.info("")
        
        # Register webhook
        webhook = service.register_webhook(
            id_model=BOURQUIN_BOARD_ID,
            callback_url=settings.webhook_callback_url,
            description="maxPrint Trello webhook - Bourquin Signs production board"
        )
        
        logger.info("✅ Webhook registered successfully!")
        logger.info("")
        logger.info(f"Webhook ID: {webhook.id}")
        logger.info(f"Status: {'Active' if webhook.active else 'Inactive'}")
        logger.info(f"Model ID: {webhook.id_model}")
        logger.info(f"Callback URL: {webhook.callback_url}")
        logger.info("")
        logger.info("=" * 60)
        logger.info("Webhook is now active and will receive events from the board")
        logger.info("=" * 60)
        
        return 0
        
    except Exception as e:
        logger.error(f"Failed to register webhook: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
