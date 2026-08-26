from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class IntegrationCreate(BaseModel):
    code: str = Field(min_length=2, max_length=60, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=120)
    provider_type: str = Field(min_length=1, max_length=60)
    status: Literal["active", "disabled", "deprecated"] = "active"


class IntegrationRead(IntegrationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class IntegrationAccountCreate(BaseModel):
    account_key: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    external_account_id: str | None = Field(default=None, max_length=255)
    status: Literal["pending", "active", "expired", "revoked", "error", "disabled"] = "pending"


class IntegrationAccountRead(IntegrationAccountCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    integration_id: str
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IntegrationCredentialUpsert(BaseModel):
    credential_type: str = Field(min_length=1, max_length=60)
    secret_reference: str = Field(min_length=1, max_length=500)
    status: Literal["active", "expired", "revoked", "error"] = "active"
    expires_at: datetime | None = None


class IntegrationCredentialRead(IntegrationCredentialUpsert):
    model_config = ConfigDict(from_attributes=True)

    id: str
    integration_account_id: str
    last_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IntegrationAccountVerify(BaseModel):
    success: bool
    external_account_id: str | None = Field(default=None, max_length=255)
    error_code: str | None = Field(default=None, max_length=120)

