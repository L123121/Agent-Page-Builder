"""页面相关的 Pydantic schemas"""

from pydantic import BaseModel, Field


class PagePayload(BaseModel):
    title: str | None = None
    description: str | None = None
    componentData: list | None = None
    canvasStyle: dict | None = None


class PageInfo(BaseModel):
    _id: str
    title: str
    description: str = ""
    userId: str | None = None
    componentData: list
    canvasStyle: dict
    shareToken: str | None = None
    isPublic: bool = False
    createdAt: str | None = None
    updatedAt: str | None = None


class PageSummary(BaseModel):
    _id: str
    title: str
    description: str = ""
    createdAt: str | None = None
    updatedAt: str | None = None
    isPublic: bool = False


class ShareResponse(BaseModel):
    shareToken: str
    shareUrl: str