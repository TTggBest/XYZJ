"""expand device runtime profiles

Revision ID: e84f3c91a72d
Revises: c61d7e843b20
Create Date: 2026-08-24 22:10:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e84f3c91a72d"
down_revision: Union[str, None] = "c61d7e843b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("device_role", sa.String(length=20), server_default="worker", nullable=False, comment="设备角色：builder、studio或worker"))
    op.add_column("devices", sa.Column("login_user", sa.String(length=120), nullable=True, comment="设备登录用户"))
    op.add_column("devices", sa.Column("thunderbolt_address", sa.String(length=45), nullable=True, comment="雷电网络地址"))
    op.add_column("devices", sa.Column("lan_address", sa.String(length=45), nullable=True, comment="普通局域网地址"))
    op.add_column("devices", sa.Column("ssh_key_path", sa.String(length=500), nullable=True, comment="SSH密钥路径"))
    op.create_unique_constraint(op.f("uq_devices_hostname"), "devices", ["hostname"])
    op.create_check_constraint("valid_device_role", "devices", "device_role IN ('builder','studio','worker')")
    comments = {
        "hostname": "设备主机名，运行包自动识别使用",
        "device_role": "设备角色：builder、studio或worker",
        "login_user": "设备登录用户",
        "thunderbolt_address": "雷电网络地址",
        "lan_address": "普通局域网地址",
        "ssh_key_path": "SSH密钥路径",
    }
    values = ",".join("(%s,%s,%s,NOW())" % (repr("devices"), repr(column), repr(comment)) for column, comment in comments.items())
    op.execute(sa.text("REPLACE INTO schema_comments (table_name,column_name,chinese_comment,updated_at) VALUES " + values))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM schema_comments WHERE table_name = 'devices' AND column_name IN ('device_role','login_user','thunderbolt_address','lan_address','ssh_key_path')"))
    op.drop_constraint("ck_devices_valid_device_role", "devices", type_="check")
    op.drop_constraint(op.f("uq_devices_hostname"), "devices", type_="unique")
    op.drop_column("devices", "ssh_key_path")
    op.drop_column("devices", "lan_address")
    op.drop_column("devices", "thunderbolt_address")
    op.drop_column("devices", "login_user")
    op.drop_column("devices", "device_role")
