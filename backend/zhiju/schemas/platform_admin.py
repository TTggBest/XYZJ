from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, StringConstraints, model_validator


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
EntityId = Annotated[str, StringConstraints(min_length=1, max_length=36)]
AccountStatus = Literal["active", "suspended"]
ManagedRole = Literal["admin", "operator", "viewer"]


class AdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewAccount(AdminInput):
    display_name: Name
    login_name: Name
    password: SecretStr = Field(min_length=1, max_length=1024)
    lease_expires_at: AwareDatetime | None = None


class TenantCreate(AdminInput):
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    short_name: Name
    lease_expires_at: AwareDatetime
    owner: NewAccount
    status: AccountStatus = "active"
    plan_code: str | None = Field(default=None, max_length=60)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=40)
    remark: str | None = None


class TenantUpdate(AdminInput):
    company_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)] | None = None
    short_name: Name | None = None
    status: AccountStatus | None = None
    lease_expires_at: AwareDatetime | None = None
    plan_code: str | None = Field(default=None, max_length=60)
    contact_name: str | None = Field(default=None, max_length=120)
    contact_phone: str | None = Field(default=None, max_length=40)
    remark: str | None = None
    suspended_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def required_fields_cannot_be_cleared(self):
        for field in {"company_name", "short_name", "status", "lease_expires_at"} & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError("主账号必填字段不能清空")
        return self


class TenantView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_name: str
    short_name: str
    status: str
    lease_expires_at: datetime
    plan_code: str | None
    contact_name: str | None
    contact_phone: str | None
    remark: str | None
    suspended_at: datetime | None
    suspended_reason: str | None


class OwnerTransfer(AdminInput):
    user_id: EntityId
    previous_owner_role: ManagedRole = "admin"


class UserCreate(NewAccount):
    role_code: ManagedRole
    status: AccountStatus = "active"


class UserUpdate(AdminInput):
    display_name: Name | None = None
    login_name: Name | None = None
    status: AccountStatus | None = None
    lease_expires_at: AwareDatetime | None = None
    suspended_reason: str | None = Field(default=None, max_length=500)
    role_code: ManagedRole | None = None
    membership_status: AccountStatus | None = None

    @model_validator(mode="after")
    def required_fields_cannot_be_cleared(self):
        for field in {"display_name", "login_name", "status", "role_code", "membership_status"} & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError("用户必填字段不能清空")
        return self


class PasswordReset(AdminInput):
    password: SecretStr = Field(min_length=1, max_length=1024)


class AccountView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    login_name: str
    status: str
    platform_role: str | None
    lease_expires_at: datetime | None


class UserView(AccountView):
    tenant_id: str
    role_code: str
    membership_status: str


class SuperAdminTransfer(AdminInput):
    user_id: EntityId | None = None
    new_user: NewAccount | None = None

    @model_validator(mode="after")
    def exactly_one_target(self):
        if (self.user_id is None) == (self.new_user is None):
            raise ValueError("必须指定现有独立账号或新建账号之一")
        return self


class DeviceBindingCreate(AdminInput):
    device_id: EntityId
    user_id: EntityId
    tenant_id: EntityId
    is_default: bool = False
    expires_at: AwareDatetime | None = None


class DeviceBindingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_id: str
    user_id: str
    tenant_id: str
    is_default: bool
    auto_login_enabled: bool
    status: str
    expires_at: datetime | None
    bound_by_user_id: str
    bound_at: datetime
    revoked_at: datetime | None
    revoke_reason: str | None


class BindingRevoke(AdminInput):
    reason: str | None = Field(default=None, max_length=500)
