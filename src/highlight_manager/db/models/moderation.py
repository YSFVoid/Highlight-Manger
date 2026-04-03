from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from highlight_manager.db.base import Base
from highlight_manager.db.models._helpers import enum_column
from highlight_manager.modules.common.enums import AuditAction, AuditEntityType, ModerationActionType
from highlight_manager.modules.common.time import utcnow


class ModerationActionModel(Base):
    __tablename__ = "moderation_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    action_type: Mapped[ModerationActionType] = enum_column(
        ModerationActionType,
        default=ModerationActionType.WARNING,
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    related_match_id: Mapped[UUID | None] = mapped_column(ForeignKey("matches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLogModel(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_guild_created", "guild_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    actor_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    target_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    entity_type: Mapped[AuditEntityType] = enum_column(AuditEntityType, default=AuditEntityType.GUILD)
    entity_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[AuditAction] = enum_column(AuditAction, default=AuditAction.QUEUE_CREATED)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
