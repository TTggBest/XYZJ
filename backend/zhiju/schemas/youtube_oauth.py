from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from zhiju.schemas.identity import ChannelRead


class YouTubeOAuthClientStatus(BaseModel):
    configured: bool
    can_manage: bool
    client_type: str | None = None
    project_id: str | None = None
    redirect_uri: str | None = None
    credential_ref: str | None = None
    scopes: list[str] = Field(default_factory=list)
    legacy_file_available: bool = False


class YouTubeAuthorizationStart(BaseModel):
    authorization_url: str
    expires_in_seconds: int


class CountryOptionRead(BaseModel):
    code: str
    name_zh: str
    recommended_language: str
    recommended_timezone: str


class YouTubeChannelImportCandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    youtube_channel_id: str
    title: str
    description: str | None
    avatar_url: str | None
    custom_url: str | None
    youtube_country_code: str | None
    youtube_default_language: str | None
    uploads_playlist_id: str | None


class YouTubeChannelImportRead(BaseModel):
    id: str
    status: str
    expires_at: datetime
    candidates: list[YouTubeChannelImportCandidateRead]
    countries: list[CountryOptionRead]


class YouTubeChannelImportSelectionPayload(BaseModel):
    candidate_id: str = Field(min_length=1)
    target_country_code: str = Field(min_length=2, max_length=2)
    default_genre: str = Field(min_length=1, max_length=120)
    operational_name: str | None = Field(default=None, max_length=255)
    default_language: str | None = Field(default=None, max_length=20)
    timezone: str | None = Field(default=None, max_length=64)


class YouTubeChannelImportCommit(BaseModel):
    selections: list[YouTubeChannelImportSelectionPayload] = Field(min_length=1)


class YouTubeChannelImportCommitResult(BaseModel):
    channels: list[ChannelRead]


class YouTubeVideoSyncResult(BaseModel):
    fetched: int
    inserted: int
    updated: int
    bound: int
    unmatched: int
