from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HelperContext(BaseModel):
    url: str = ""
    pageTitle: str = ""
    referrer: str = ""
    signedIn: bool = False


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=2000)


class HelperChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    selectedPrompt: str = ""
    visitorId: str = ""
    threadId: str = ""
    history: list[ChatTurn] = Field(default_factory=list)
    context: HelperContext = Field(default_factory=HelperContext)


class SourceOut(BaseModel):
    title: str
    url: str
    kind: str


class HelperChatResponse(BaseModel):
    answer: str
    threadId: str
    sources: list[SourceOut]
    usage: dict[str, Any] = Field(default_factory=dict)
