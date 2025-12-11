from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TrelloSettings(BaseSettings):
    trello_key: str = Field(..., alias="TRELLO_KEY")
    trello_token: str = Field(..., alias="TRELLO_TOKEN")
    webhook_callback_url: str = Field(..., alias="TRELLO_WEBHOOK_CALLBACK_URL")
    test_board_id: str | None = Field(None, alias="TRELLO_TEST_BOARD_ID")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


class TrelloWebhookMeta(BaseModel):
    """Metadata about a registered webhook."""

    id: str
    description: str | None = None
    id_model: str | None = Field(None, alias="idModel")
    callback_url: str | None = Field(None, alias="callbackURL")
    active: bool | None = None

    model_config = {"populate_by_name": True}
