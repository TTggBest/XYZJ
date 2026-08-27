from pydantic import BaseModel, Field


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

