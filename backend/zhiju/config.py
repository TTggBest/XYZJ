from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


APP_ROOT = Path(__file__).resolve().parents[2]


def validate_cloud_database_url(value: str, *, label: str) -> None:
    url = make_url(value)
    if url.database != "zhiju_cloud":
        raise ValueError(f"云端 {label} 必须指向 zhiju_cloud")
    query_keys = {key.lower() for key in url.normalized_query}
    if query_keys & {"unix_socket", "socket"}:
        raise ValueError(f"云端 {label} 只允许本机 TCP 连接")
    host = (url.host or "").strip().lower().rstrip(".")
    if host == "localhost":
        return
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ValueError(f"云端 {label} 只允许本机 TCP 连接") from exc
    if address not in {ip_address("127.0.0.1"), ip_address("::1")}:
        raise ValueError(f"云端 {label} 只允许本机 TCP 连接")


class FeishuScheduleSource(BaseModel):
    wiki_token: str = Field(min_length=1)
    directory_sheet_id: str = Field(min_length=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=APP_ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="ZHJ_",
        case_sensitive=False,
        extra="ignore",
    )

    env: str = "development"
    deployment: Literal["local", "cloud"] = "local"
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
    feishu_drama_library_wiki_token: str = "KNxew7DIUiNr6ukbgYrciIqongh"
    feishu_channel_schedule_wiki_token: str = "ErwWwX8TVionsikFwQMcEpCenih"
    feishu_channel_schedule_directory_sheet_id: str = "2FrKIE"
    feishu_channel_schedule_sources: dict[str, FeishuScheduleSource] = Field(default_factory=dict)
    zhihe_api_base_url: str = ""
    zhihe_api_token: str = ""
    youtube_oauth_client_id: str = ""
    youtube_oauth_client_secret: str = ""
    youtube_oauth_redirect_uri: str = (
        "https://xyzj.chronaraxy.com/api/v3/youtube/oauth/callback"
    )
    oauth_encryption_key: str = ""
    google_proxy_url: str = ""

    @property
    def youtube_oauth_configured(self) -> bool:
        return bool(
            self.youtube_oauth_client_id.strip()
            and self.youtube_oauth_client_secret.strip()
            and self.oauth_encryption_key.strip()
            and self.youtube_oauth_redirect_uri.startswith("https://")
        )

    @model_validator(mode="after")
    def validate_cloud_contract(self):
        if self.deployment != "cloud":
            return self
        if self.env != "production":
            raise ValueError("云端部署必须保持 ZHJ_ENV=production")
        if self.host != "127.0.0.1":
            raise ValueError("云端 Uvicorn 必须仅监听 127.0.0.1")
        validate_cloud_database_url(self.database_url, label="ZHJ_DATABASE_URL")
        if self.migration_database_url:
            validate_cloud_database_url(
                self.migration_database_url, label="ZHJ_MIGRATION_DATABASE_URL"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
