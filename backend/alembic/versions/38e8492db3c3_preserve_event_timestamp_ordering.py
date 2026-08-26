"""preserve event timestamp ordering

Revision ID: 38e8492db3c3
Revises: 0448c579cfab
Create Date: 2026-08-16 19:08:07.085283
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = '38e8492db3c3'
down_revision: Union[str, None] = '0448c579cfab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = (
        ("audit_events", "occurred_at", "操作发生时间"),
        ("authorization_events", "occurred_at", "事件发生时间"),
        ("task_events", "occurred_at", "事件时间"),
        ("system_events", "occurred_at", "事件发生时间"),
        ("schedule_change_history", "changed_at", "调整时间"),
        ("youtube_video_status_history", "changed_at", "状态变化时间"),
    )
    for table_name, column_name, comment in columns:
        op.alter_column(
            table_name,
            column_name,
            existing_type=mysql.DATETIME(),
            type_=mysql.DATETIME(fsp=6),
            existing_nullable=False,
            existing_comment=comment,
        )


def downgrade() -> None:
    columns = (
        ("audit_events", "occurred_at", "操作发生时间"),
        ("authorization_events", "occurred_at", "事件发生时间"),
        ("task_events", "occurred_at", "事件时间"),
        ("system_events", "occurred_at", "事件发生时间"),
        ("schedule_change_history", "changed_at", "调整时间"),
        ("youtube_video_status_history", "changed_at", "状态变化时间"),
    )
    for table_name, column_name, comment in columns:
        op.alter_column(
            table_name,
            column_name,
            existing_type=mysql.DATETIME(fsp=6),
            type_=mysql.DATETIME(),
            existing_nullable=False,
            existing_comment=comment,
        )
