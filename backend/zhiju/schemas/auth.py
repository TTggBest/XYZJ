from pydantic import BaseModel, Field, SecretStr


class PasswordLogin(BaseModel):
    login_name: str = Field(min_length=1, max_length=120)
    password: SecretStr


class TenantSwitch(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=36)


class CurrentTenant(BaseModel):
    id: str
    company_name: str
    short_name: str


class AvailableMembership(BaseModel):
    tenant_id: str
    company_name: str
    short_name: str
    role_code: str


class CurrentDevice(BaseModel):
    id: str
    name: str
    display_name: str
    trust_level: str


class CurrentUser(BaseModel):
    user_id: str
    display_name: str
    login_name: str
    platform_role: str | None
    tenant_id: str | None
    membership_role: str | None
    current_tenant: CurrentTenant | None
    memberships: list[AvailableMembership]
    switchable_tenants: list[CurrentTenant]
    device: CurrentDevice | None
    permissions: list[str]


class LogoutResult(BaseModel):
    status: str = "ok"
