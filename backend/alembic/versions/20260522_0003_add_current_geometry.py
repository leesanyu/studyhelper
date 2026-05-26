# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""add current geometry to chat sessions

Revision ID: 20260522_0003
Revises: 20260520_0002
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa

revision = "20260522_0003"
down_revision = "20260520_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(sa.Column("current_geometry", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("current_geometry")
