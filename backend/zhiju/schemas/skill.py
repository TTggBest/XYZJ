from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


SkillStatus = Literal["active", "disabled", "deprecated"]
SkillVersionStatus = Literal["draft", "published", "superseded", "archived"]


class SkillCreate(BaseModel):
    code: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
    purpose: str = Field(min_length=1)
    category: str = Field(min_length=1, max_length=60)
    status: SkillStatus = "active"


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    purpose: str | None = Field(default=None, min_length=1)
    category: str | None = Field(default=None, min_length=1, max_length=60)
    status: SkillStatus | None = None


class SkillRead(SkillCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class SkillVersionCreate(BaseModel):
    body_zh_cn: str = Field(min_length=1)
    body_original: str = Field(min_length=1)
    change_summary: str | None = None
    created_by: str | None = Field(default=None, max_length=120)


class SkillVersionUpdate(BaseModel):
    body_zh_cn: str | None = Field(default=None, min_length=1)
    body_original: str | None = Field(default=None, min_length=1)
    change_summary: str | None = None
    created_by: str | None = Field(default=None, max_length=120)


class SkillVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    skill_id: str
    version_number: int
    body_zh_cn: str
    body_original: str
    content_sha256: str
    status: SkillVersionStatus
    is_current: bool | None
    change_summary: str | None
    created_by: str | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SkillDetail(SkillRead):
    current_version: SkillVersionRead | None
