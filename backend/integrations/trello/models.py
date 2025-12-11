from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TrelloBoard(BaseModel):
    id: str
    name: Optional[str] = None
    short_link: Optional[str] = Field(None, alias="shortLink")
    id_organization: Optional[str] = Field(None, alias="idOrganization")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class TrelloList(BaseModel):
    id: str
    name: Optional[str] = None
    id_board: Optional[str] = Field(None, alias="idBoard")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class TrelloCard(BaseModel):
    id: str
    name: Optional[str] = None
    id_list: Optional[str] = Field(None, alias="idList")
    id_board: Optional[str] = Field(None, alias="idBoard")
    short_link: Optional[str] = Field(None, alias="shortLink")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class TrelloMember(BaseModel):
    id: str
    full_name: Optional[str] = Field(None, alias="fullName")
    username: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class TrelloActionData(BaseModel):
    board: Optional[TrelloBoard] = None
    card: Optional[TrelloCard] = None
    list: Optional[TrelloList] = None
    list_before: Optional[TrelloList] = Field(None, alias="listBefore")
    list_after: Optional[TrelloList] = Field(None, alias="listAfter")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class TrelloAction(BaseModel):
    id: str
    type: Optional[str] = None
    date: Optional[str] = None
    data: TrelloActionData
    member_creator: Optional[TrelloMember] = Field(None, alias="memberCreator")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class TrelloModel(BaseModel):
    id: str
    name: Optional[str] = None
    short_link: Optional[str] = Field(None, alias="shortLink")

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class TrelloWebhookPayload(BaseModel):
    action: TrelloAction
    model: Optional[TrelloModel] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    @property
    def idempotency_key(self) -> str:
        return self.action.id


class TrelloWebhookResponse(BaseModel):
    status: str
    action_id: str
    action_type: Optional[str] = None
    board_id: Optional[str] = None
    card_id: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

