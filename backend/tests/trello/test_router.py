from fastapi import FastAPI
from fastapi.testclient import TestClient

from integrations.trello.models import TrelloAction
from integrations.trello.router import get_trello_router


class StubPublisher:
    def __init__(self) -> None:
        self.actions: list[TrelloAction] = []

    async def publish(self, action: TrelloAction) -> None:
        self.actions.append(action)


def build_client(publisher: StubPublisher) -> TestClient:
    app = FastAPI()
    app.include_router(get_trello_router(publisher=publisher))
    return TestClient(app)


def test_verification_endpoints():
    publisher = StubPublisher()
    client = build_client(publisher)

    assert client.get("/trello/webhook").status_code == 200
    assert client.head("/trello/webhook").status_code == 200


def test_valid_webhook_invokes_publisher():
    publisher = StubPublisher()
    client = build_client(publisher)

    payload = {
        "action": {
            "id": "act123",
            "type": "updateCard",
            "date": "2024-01-01T00:00:00.000Z",
            "data": {
                "card": {"id": "card1", "name": "Test Card"},
                "board": {"id": "board1", "name": "Test Board"},
            },
        }
    }

    response = client.post("/trello/webhook", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["action_id"] == "act123"
    assert len(publisher.actions) == 1
    assert publisher.actions[0].id == "act123"


def test_invalid_payload_returns_400():
    publisher = StubPublisher()
    client = build_client(publisher)

    response = client.post("/trello/webhook", json={"not_action": {}})
    assert response.status_code == 400
