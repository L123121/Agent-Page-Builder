"""认证相关的 Pydantic schemas"""

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=20)
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class UserInfo(BaseModel):
    _id: str
    username: str
    email: str
    avatar: str = ""
    createdAt: str | None = None
    updatedAt: str | None = None


class AuthResponse(BaseModel):
    token: str
    user: UserInfo