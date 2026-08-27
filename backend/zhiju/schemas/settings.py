from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuntimePackageBuildRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    build_number: int
    version: str
    target_environment: str
    status: str
    artifact_path: str | None
    file_count: int
    size_bytes: int
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class RuntimeOverview(BaseModel):
    system: str
    version: str
    environment: str
    base_environment: str
    can_switch_environment: bool
    host: str
    port: int
    database_host: str
    database_port: int | None
    database_name: str
    database_ok: bool
    project_root: str
    artifact_root: str
    hostname: str
    operating_system: str
    architecture: str
    python_version: str
    device_role: str
    realtime_hub_url: str


class RuntimeEnvironmentUpdate(BaseModel):
    environment: Literal["development", "production"]


class AppIconUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    data_url: str = Field(min_length=100, max_length=15_000_000)


class AppIconSettingRead(BaseModel):
    id: str
    source_type: str
    original_filename: str | None
    preview_url: str
    desktop_app_path: str
    applied_at: datetime
    updated_at: datetime
