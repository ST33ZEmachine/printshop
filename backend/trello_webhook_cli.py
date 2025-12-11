"""
Utility CLI for Trello webhook management (non-destructive).
"""

import argparse
import logging

from integrations.trello.config import TrelloSettings
from integrations.trello.service import TrelloService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Trello webhooks for dev/test.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register", help="Register a webhook for the test board.")
    register.add_argument("--board-id", help="Board ID to register against (defaults to TRELLO_TEST_BOARD_ID).")
    register.add_argument("--callback-url", help="Callback URL (defaults to TRELLO_WEBHOOK_CALLBACK_URL).")
    register.add_argument("--description", help="Optional description for the webhook.")

    subparsers.add_parser("list", help="List webhooks for the current token.")

    delete_cmd = subparsers.add_parser("delete", help="Delete a webhook by id (cleanup only).")
    delete_cmd.add_argument("webhook_id", help="Webhook ID to delete.")

    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = build_parser()
    args = parser.parse_args()

    settings = TrelloSettings()
    service = TrelloService(settings=settings)

    if args.command == "register":
        board_id = args.board_id or settings.test_board_id
        callback_url = args.callback_url or settings.webhook_callback_url
        if not board_id or not callback_url:
            parser.error("board-id and callback-url (or env vars) are required.")
        webhook = service.register_webhook(
            id_model=board_id,
            callback_url=callback_url,
            description=args.description,
        )
        print(f"Registered webhook: {webhook.id} -> {webhook.callback_url}")  # noqa: T201
    elif args.command == "list":
        webhooks = service.list_webhooks()
        for hook in webhooks:
            print(f"{hook.id} | active={hook.active} | model={hook.id_model} | callback={hook.callback_url}")  # noqa: T201
    elif args.command == "delete":
        service.delete_webhook(args.webhook_id)
        print(f"Deleted webhook {args.webhook_id}")  # noqa: T201
    else:  # pragma: no cover - argparse guards commands
        parser.error("Unknown command")


if __name__ == "__main__":
    main()

