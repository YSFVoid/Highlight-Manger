from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from highlight_manager.db.base import Base
from highlight_manager.db.models._helpers import TimestampMixin, enum_column
from highlight_manager.modules.common.enums import ActivityKind, RoleKind


class GuildModel(TimestampMixin, Base):
    __tablename__ = "guilds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)


class GuildSettingModel(TimestampMixin, Base):
    __tablename__ = "guild_settings"

    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), primary_key=True)
    current_season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"), nullable=True)
    prefix: Mapped[str] = mapped_column(String(8), nullable=False, default="!")
    persistent_voice_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    persistent_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    persistent_voice_auto_rejoin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    persistent_voice_self_deaf: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result_category_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    match_category_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    waiting_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    waiting_voice_channel_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    apostado_channel_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    highlight_channel_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    esport_channel_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    apostado_match_ping_target: Mapped[str] = mapped_column(String(64), nullable=False, default="here")
    highlight_match_ping_target: Mapped[str] = mapped_column(String(64), nullable=False, default="here")
    esport_match_ping_target: Mapped[str] = mapped_column(String(64), nullable=False, default="here")
    queue_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    room_info_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    result_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)
    default_ruleset_key: Mapped[str] = mapped_column(String(32), nullable=False, default="apostado")


class GuildStaffRoleModel(Base):
    __tablename__ = "guild_staff_roles"
    __table_args__ = (
        UniqueConstraint("guild_id", "role_id", "role_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    role_kind: Mapped[RoleKind] = enum_column(RoleKind, default=RoleKind.MODERATOR)


class PlayerModel(TimestampMixin, Base):
    __tablename__ = "players"
    __table_args__ = (
        UniqueConstraint("guild_id", "discord_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    global_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    joined_guild_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PlayerActivityStateModel(Base):
    __tablename__ = "player_activity_states"
    __table_args__ = (
        CheckConstraint(
            """
            (activity_kind = 'idle' and queue_id is null and match_id is null and tournament_id is null)
            or (activity_kind = 'queue' and queue_id is not null and match_id is null and tournament_id is null)
            or (activity_kind = 'match' and queue_id is null and match_id is not null and tournament_id is null)
            or (activity_kind = 'tournament' and queue_id is null and match_id is null and tournament_id is not null)
            """,
            name="player_activity_state_matches_kind",
        ),
        Index("ix_player_activity_states_queue_id", "queue_id"),
        Index("ix_player_activity_states_match_id", "match_id"),
    )

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"),
        primary_key=True,
    )
    activity_kind: Mapped[ActivityKind] = enum_column(ActivityKind, default=ActivityKind.IDLE)
    queue_id: Mapped[UUID | None] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=True)
    match_id: Mapped[UUID | None] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=True)
    tournament_id: Mapped[UUID | None] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
