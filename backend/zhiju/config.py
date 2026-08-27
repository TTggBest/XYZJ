from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


APP_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=APP_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="ZHJ_",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = "development"
    database_url: str = Field(min_length=1)
    migration_database_url: str | None = None
    host: str = "127.0.0.1"
    port: int = 19732
    log_level: str = "INFO"
    artifact_root: Path = APP_ROOT / ".runtime" / "artifacts"
    device_id: str = ""
    device_role: str = "builder"
    device_key: str = ""
    realtime_hub_url: str = ""
    shared_root: Path | None = None
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_wiki_token: str = "UQYlwFa2piv9AVkQDTTc0mQznHh"
    feishu_work_order_sheet_id: str = "Lgm70y"
    feishu_operation_package_sheet_id: str = "aJGsjJ"
    feishu_channel_master_sheet_id: str = "7b1e16"
    feishu_channel_info_sheet_id: str = "CMo2j2"
    feishu_channel_branding_sheet_id: str = "NYJWdE"
    feishu_drama_wiki_token: str = "TzkWwanAAikv7pkOJcTcddiVnoh"
    feishu_drama_sheet_title: str = "剧库表"


@lru_cache
def get_settings() -> Settings:
    return Settings()
