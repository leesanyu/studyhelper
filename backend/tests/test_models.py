# Copyright (C) 2026 LIHUO. All rights reserved.
#
# This file is released under the MIT License.

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import Asset, ChatMessage, ChatSession, User, UserTagHistory


def test_core_tables_support_chat_and_asset_persistence():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(engine, expire_on_commit=False)
    with session_factory() as session:
        user = User(anonymous_id="anon-1", display_name="Anonymous")
        session.add(user)
        session.flush()

        chat_session = ChatSession(
            user_id=user.id,
            title="几何题",
            status="active",
            current_question="求角度关系",
            current_diagram="A, B, C are connected",
            current_knowledge={"subject": "初中数学", "points": ["角平分线"]},
            current_geometry={"version": "1.0", "given_relations": []},
        )
        session.add(chat_session)
        session.flush()

        message = ChatMessage(
            session_id=chat_session.id,
            role="assistant",
            content="角度关系为 ...",
            mode="direct",
            knowledge_points=["角平分线"],
            raw_metadata={"source": "mock"},
        )
        session.add(message)
        session.flush()

        asset = Asset(
            user_id=user.id,
            session_id=chat_session.id,
            message_id=message.id,
            asset_type="sandbox_image",
            storage_backend="local",
            object_key="figures/1.png",
            url="/assets/figures/1.png",
            filename="1.png",
            mime_type="image/png",
            size_bytes=128,
            width=640,
            height=480,
        )
        tag = UserTagHistory(
            user_id=user.id,
            session_id=chat_session.id,
            message_id=message.id,
            subject="初中数学",
            knowledge_point="角平分线",
            source="agent",
        )
        session.add_all([asset, tag])
        session.commit()

    with session_factory() as session:
        stored_session = session.execute(
            select(ChatSession).where(ChatSession.title == "几何题")
        ).scalar_one()
        stored_message = session.execute(
            select(ChatMessage).where(ChatMessage.content.contains("角度关系"))
        ).scalar_one()
        stored_asset = session.execute(
            select(Asset).where(Asset.object_key == "figures/1.png")
        ).scalar_one()
        stored_tag = session.execute(
            select(UserTagHistory).where(UserTagHistory.knowledge_point == "角平分线")
        ).scalar_one()

    assert stored_session.current_knowledge["subject"] == "初中数学"
    assert stored_session.current_geometry["version"] == "1.0"
    assert stored_message.knowledge_points == ["角平分线"]
    assert stored_asset.session_id == stored_session.id
    assert stored_asset.message_id == stored_message.id
    assert stored_tag.user_id == stored_session.user_id
