from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["ADMIN", "AGENT"]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TeamRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: Role
    team: TeamRef | None
    is_active: bool
    source: str
    supervisor: str | None
    last_login_at: datetime | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


def _strong(password: str) -> str:
    if len(password) < 10 or not any(c.isdigit() for c in password) or not any(c.isalpha() for c in password):
        raise ValueError("Use at least 10 characters with letters and digits")
    return password


class UserCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    role: Role = "AGENT"
    team_id: int | None = None

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str) -> str:
        return _strong(v)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    role: Role | None = None
    team_id: int | None = None
    clear_team: bool = False
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=256)

    @field_validator("password")
    @classmethod
    def _pw(cls, v: str | None) -> str | None:
        return None if v is None else _strong(v)


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    department: DepartmentOut
    member_count: int = 0
    categories: list[str] = []


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    department_id: int
    description: str | None = Field(default=None, max_length=2000)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    department_id: int | None = None
    description: str | None = Field(default=None, max_length=2000)


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    team: TeamRef | None
    base_priority: str = "Medium"
    # The 12 dataset categories: the classifier predicts these names and the priority rules key on them.
    builtin: bool = False


class CategoryCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    team_id: int | None = None


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=64)
    description: str | None = Field(default=None, max_length=2000)
    team_id: int | None = None
    clear_team: bool = False


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None
    action: str
    resource_type: str | None
    resource_id: str | None
    metadata: dict | None = Field(default=None, validation_alias="metadata_")
    created_at: datetime
