#!/usr/bin/env python3
"""
Test Trello API access and list available boards.

Usage:
    python test_trello_access.py                    # List all accessible boards
    python test_trello_access.py --board-id <id>     # Test specific board
    python test_trello_access.py --board-id <id> --card-id <id>  # Test board and card
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Also try in backend directory
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from integrations.trello.config import TrelloSettings
from integrations.trello.service import TrelloService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def list_boards(service: TrelloService):
    """List all accessible boards."""
    logger.info("=" * 60)
    logger.info("Listing Accessible Trello Boards")
    logger.info("=" * 60)
    logger.info("")
    
    try:
        boards = service.list_boards()
        
        if not boards:
            logger.info("No boards found. You may not have access to any boards.")
            return
        
        logger.info(f"Found {len(boards)} accessible board(s):")
        logger.info("")
        
        for i, board in enumerate(boards, 1):
            closed_status = "🔒 CLOSED" if board.get('closed') else "✅ OPEN"
            org = board.get('idOrganization') or "Personal"
            
            logger.info(f"{i}. {board.get('name', 'Unnamed')}")
            logger.info(f"   ID: {board.get('id')}")
            logger.info(f"   Status: {closed_status}")
            logger.info(f"   Organization: {org}")
            logger.info(f"   URL: {board.get('url', 'N/A')}")
            logger.info("")
        
        logger.info("=" * 60)
        logger.info("To test a specific board, run:")
        logger.info(f"  python test_trello_access.py --board-id <board_id>")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ FAILED: Cannot list boards")
        logger.error(f"   Error: {e}")
        logger.error("")
        logger.error("Possible issues:")
        logger.error("   1. API key/token is incorrect")
        logger.error("   2. Token doesn't have read permissions")
        raise


def test_board(service: TrelloService, board_id: str, card_id: str = None):
    """Test access to a specific board."""
    logger.info("=" * 60)
    logger.info("Testing Trello API Access")
    logger.info("=" * 60)
    logger.info(f"Board ID: {board_id}")
    logger.info("")
    
    # Test 1: Get board info
    logger.info("Test 1: Fetching board information...")
    try:
        board = service.get_board(board_id)
        logger.info("✅ SUCCESS: Board access confirmed!")
        logger.info(f"   Board Name: {board.get('name')}")
        logger.info(f"   Board URL: {board.get('url')}")
        logger.info(f"   Closed: {board.get('closed', False)}")
        logger.info("")
    except Exception as e:
        logger.error(f"❌ FAILED: Cannot access board")
        logger.error(f"   Error: {e}")
        logger.error("")
        logger.error("Possible issues:")
        logger.error("   1. Your account doesn't have access to this board")
        logger.error("   2. API key/token is incorrect")
        logger.error("   3. Token doesn't have read permissions")
        return 1
    
    # Test 2: Fetch a card (if provided)
    if card_id:
        logger.info(f"Test 2: Fetching card {card_id}...")
        try:
            card = service.fetch_card(card_id)
            logger.info("✅ SUCCESS: Card access confirmed!")
            logger.info(f"   Card Name: {card.get('name')}")
            logger.info(f"   Card ID: {card.get('id')}")
            logger.info(f"   List ID: {card.get('idList')}")
            logger.info("")
        except Exception as e:
            logger.error(f"❌ FAILED: Cannot access card")
            logger.error(f"   Error: {e}")
            return 1
    
    logger.info("=" * 60)
    logger.info("All tests passed! Your API key/token works with this board.")
    logger.info("=" * 60)
    return 0


def main():
    parser = argparse.ArgumentParser(description="Test Trello API access and list boards")
    parser.add_argument(
        "--board-id",
        help="Optional: Test access to a specific board ID"
    )
    parser.add_argument(
        "--card-id",
        help="Optional: Test fetching a specific card (requires --board-id)"
    )
    
    args = parser.parse_args()
    
    try:
        # Load settings
        settings = TrelloSettings()
        service = TrelloService(settings)
        
        # If board-id provided, test that board
        if args.board_id:
            return test_board(service, args.board_id, args.card_id)
        else:
            # Otherwise, list all boards
            list_boards(service)
            return 0
        
    except Exception as e:
        logger.error(f"Configuration error: {e}")
        logger.error("")
        logger.error("Make sure you have set:")
        logger.error("  - TRELLO_KEY environment variable")
        logger.error("  - TRELLO_TOKEN environment variable")
        return 1


if __name__ == "__main__":
    sys.exit(main())
