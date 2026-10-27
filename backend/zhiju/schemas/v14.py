from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class V14SettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host_id: str = Field(min_length=1, max_length=36)
    account_profile: str = Field(default="current", min_length=1, max_length=120)
    default_model: str = Field(min_length=1, max_length=120)
    available_models: list[str] = Field(default_factory=list)
    rules: dict = Field(default_factory=dict)
    channel_inputs: dict[str, dict] = Field(default_factory=dict)
    workflow_version_id: str = 'builtin-v14'


class ClaimRequest(BaseModel):
    host_id: str
    executor_protocol: int = 1


class AttemptStart(BaseModel):
    claim_id: str
    node_type: Literal["search", "title", "cover", "description", "community", "merge"]


class AttemptSubmission(BaseModel):
    claim_id: str
    outcome: Literal["accepted", "content_error", "system_error"]
    result: dict | None = None
    error: str | None = Field(default=None, max_length=4000)


class ResumeRequest(BaseModel):
    stopped_confirmed: bool = False


class ClaimIdentity(BaseModel):
    claim_id: str
