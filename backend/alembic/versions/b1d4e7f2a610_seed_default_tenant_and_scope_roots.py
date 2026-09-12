"""seed default tenant and scope roots

Revision ID: b1d4e7f2a610
Revises: a9c4e7b2d613
"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1d4e7f2a610"
down_revision: Union[str, None] = "a9c4e7b2d613"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_EXISTING_TENANT_ID = "00000000-0000-4000-8000-000000000001"
ROOT_TABLES = (
    "channels", "dramas", "production_batches", "google_accounts",
    "integration_accounts", "channel_drama_types", "image_workspace_settings",
    "demo_data_batches", "feishu_sync_runs", "media_assets", "audit_events",
    "system_events", "api_request_logs", "quota_usage_logs",
)
AUTH_REFERENCE_TABLES = (
    "tenant_memberships", "device_user_bindings", "auth_sessions", "auth_events",
)
PERMISSIONS = {
    "tenant.read": "查看主账号",
    "tenant.manage": "管理主账号",
    "user.read": "查看用户",
    "user.manage": "管理用户",
    "channel.read": "查看频道",
    "channel.manage": "管理频道",
    "channel.delete": "永久删除频道",
    "schedule.manage": "管理排期",
    "workorder.manage": "管理工单",
    "package.manage": "管理运营包",
    "media.manage": "管理素材",
    "youtube.sync": "同步 YouTube",
    "audit.read": "查看审计记录",
    "platform.tenant.manage": "管理平台主账号",
    "platform.device.manage": "管理平台设备",
    "platform.environment.manage": "管理运行环境",
}
ROLE_PERMISSIONS = {
    "super_admin": tuple(PERMISSIONS),
    "owner": tuple(code for code in PERMISSIONS if not code.startswith("platform.")),
    "admin": (
        "tenant.read", "user.read", "user.manage", "channel.read", "channel.manage",
        "schedule.manage", "workorder.manage", "package.manage", "media.manage",
        "youtube.sync", "audit.read",
    ),
    "operator": (
        "tenant.read", "channel.read", "schedule.manage", "workorder.manage",
        "package.manage", "media.manage", "youtube.sync",
    ),
    "viewer": ("tenant.read", "user.read", "channel.read", "audit.read"),
}
ROLE_ID_PREFIXES = {"super_admin": "sa:", "owner": "ow:", "admin": "ad:", "operator": "op:", "viewer": "vw:"}


def _seed_default_tenant_and_permissions() -> None:
    tenants = sa.table(
        "tenants", sa.column("id", sa.String(36)), sa.column("company_name", sa.String(255)),
        sa.column("short_name", sa.String(120)), sa.column("status", sa.String(20)),
        sa.column("lease_expires_at", sa.DateTime()),
    )
    op.execute(tenants.insert().from_select(
        ["id", "company_name", "short_name", "status", "lease_expires_at"],
        sa.select(
            sa.literal(DEFAULT_EXISTING_TENANT_ID), sa.literal("智矩现有业务"),
            sa.literal("智矩现有业务"), sa.literal("active"),
            # MySQL DATETIME stores the agreed UTC value without a timezone suffix.
            sa.literal(datetime(2099, 12, 31, 23, 59, 59)),
        ).where(~sa.exists().where(tenants.c.id == DEFAULT_EXISTING_TENANT_ID)),
    ))
    permissions = sa.table(
        "permissions", sa.column("id", sa.String(36)), sa.column("code", sa.String(120)),
        sa.column("name_zh", sa.String(120)),
    )
    role_permissions = sa.table(
        "role_permissions", sa.column("id", sa.String(36)),
        sa.column("role_code", sa.String(20)), sa.column("permission_id", sa.String(36)),
    )
    for code, name in PERMISSIONS.items():
        op.execute(permissions.insert().from_select(
            ["id", "code", "name_zh"],
            sa.select(sa.literal(code), sa.literal(code), sa.literal(name)).where(
                ~sa.exists().where(permissions.c.code == code)
            ),
        ))
    for role, codes in ROLE_PERMISSIONS.items():
        for code in codes:
            permission_id = sa.select(permissions.c.id).where(permissions.c.code == code).scalar_subquery()
            op.execute(role_permissions.insert().from_select(
                ["id", "role_code", "permission_id"],
                sa.select(sa.literal(ROLE_ID_PREFIXES[role] + code), sa.literal(role), permission_id).where(
                    ~sa.exists().where(
                        role_permissions.c.role_code == role,
                        role_permissions.c.permission_id == permission_id,
                    )
                ),
            ))


def upgrade() -> None:
    _seed_default_tenant_and_permissions()
    for name in ROOT_TABLES:
        op.add_column(name, sa.Column("tenant_id", sa.String(36), nullable=True, comment="所属主账号ID"))
        op.create_index(f"ix_{name}_tenant_id", name, ["tenant_id"], unique=False)
        table = sa.table(name, sa.column("tenant_id", sa.String(36)))
        op.execute(table.update().where(table.c.tenant_id.is_(None)).values(tenant_id=DEFAULT_EXISTING_TENANT_ID))


def downgrade() -> None:
    connection = op.get_bind()
    # Check every current tenant reference before any MySQL DDL can commit.
    for name in ROOT_TABLES + AUTH_REFERENCE_TABLES:
        table = sa.table(name, sa.column("tenant_id", sa.String(36)))
        # Dropping root columns must not discard another tenant's ownership either.
        condition = (table.c.tenant_id.is_not(None) if name in ROOT_TABLES
                     else table.c.tenant_id == DEFAULT_EXISTING_TENANT_ID)
        referenced = connection.scalar(
            sa.select(sa.literal(1)).select_from(table).where(condition).limit(1)
        )
        if referenced is not None:
            raise RuntimeError(f"拒绝回退租户迁移：{name} 仍存在业务引用")
    for name in reversed(ROOT_TABLES):
        op.drop_index(f"ix_{name}_tenant_id", table_name=name)
        op.drop_column(name, "tenant_id")
    tenants = sa.table("tenants", sa.column("id", sa.String(36)))
    op.execute(tenants.delete().where(tenants.c.id == DEFAULT_EXISTING_TENANT_ID))
    # Permission codes and grants are shared catalog data; preserve existing use.
