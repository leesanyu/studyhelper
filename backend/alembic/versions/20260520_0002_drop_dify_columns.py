# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

"""drop dify columns

Revision ID: 20260520_0002
Revises: 20260509_0001
Create Date: 2026-05-20
"""

from alembic import op

revision = "20260520_0002"
down_revision = "20260509_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_index("ix_chat_sessions_dify_conversation_id")
        batch_op.drop_column("dify_conversation_id")

    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.drop_index("ix_chat_messages_dify_message_id")
        batch_op.drop_column("dify_message_id")

    with op.batch_alter_table("assets") as batch_op:
        batch_op.drop_index("ix_assets_dify_file_id")
        batch_op.drop_column("dify_file_id")


def downgrade() -> None:
    import sqlalchemy as sa

    with op.batch_alter_table("assets") as batch_op:
        batch_op.add_column(sa.Column("dify_file_id", sa.String(128), nullable=True))
        batch_op.create_index("ix_assets_dify_file_id", ["dify_file_id"], unique=False)

    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.add_column(sa.Column("dify_message_id", sa.String(128), nullable=True))
        batch_op.create_index("ix_chat_messages_dify_message_id", ["dify_message_id"], unique=True)

    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(sa.Column("dify_conversation_id", sa.String(128), nullable=True))
        batch_op.create_index("ix_chat_sessions_dify_conversation_id", ["dify_conversation_id"], unique=True)
