from datetime import datetime

from pydantic import BaseModel, field_validator
from typing import Optional


class UserRegister(BaseModel):
    email: str
    password: str
    name: Optional[str] = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("邮箱格式不正确，请输入有效的邮箱地址（如 name@example.com）")
        return v


class UserLogin(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip()
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("邮箱格式不正确，请输入有效的邮箱地址（如 name@example.com）")
        return v


class UserResponse(BaseModel):
    id: str
    email: str
    name: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse
