from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from highlight_manager.db.base import Base
from highlight_manager.db.models._helpers import TimestampMixin, enum_column
from highlight_manager.modules.common.enums import (
    MatchMode,
    MatchPlayerResult,
    MatchResultPhase,
    MatchState,
    QueueState,
    RatingReason,
    RulesetKey,
    SeasonStatus,
)
from highlight_manager.modules.common.time import utcnow


class SeasonModel(TimestampMixin, Base):
    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("guild_id", "season_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[SeasonStatus] = enum_column(SeasonStatus, default=SeasonStatus.ACTIVE)
    ranked_queue_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RankTierModel(Base):
    __tablename__ = "rank_tiers"
    __table_args__ = (
        UniqueConstraint("guild_id", "code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    min_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    max_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    accent_hex: Mapped[str | None] = mapped_column(String(16), nullable=True)
    badge_asset_key: Mapped[str | None] = mapped_column(String(120), nullable=True)


class SeasonPlayerModel(TimestampMixin, Base):
    __tablename__ = "season_players"
    __table_args__ = (
        UniqueConstraint("season_id", "player_id"),
        Index(
            "ix_season_players_leaderboard",
            "season_id",
            "rating",
            "wins",
            "peak_rating",
            "matches_played",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    seed_rating: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    rating: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matches_played: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    peak_rating: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    current_tier_id: Mapped[int | None] = mapped_column(ForeignKey("rank_tiers.id"), nullable=True)
    final_leaderboard_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    legacy_points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    legacy_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QueueModel(Base):
    __tablename__ = "queues"
    __table_args__ = (
        Index("ix_queues_state_deadline", "state", "room_info_deadline_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False)
    creator_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    ruleset_key: Mapped[RulesetKey] = enum_column(RulesetKey, default=RulesetKey.APOSTADO)
    mode: Mapped[MatchMode] = enum_column(MatchMode, default=MatchMode.TWO_V_TWO)
    state: Mapped[QueueState] = enum_column(QueueState, default=QueueState.QUEUE_OPEN)
    team_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    public_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    room_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    room_password: Mapped[str | None] = mapped_column(String(128), nullable=True)
    room_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    room_info_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    room_info_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    room_info_submitted_by_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    converted_match_id: Mapped[UUID | None] = mapped_column(ForeignKey("matches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    full_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QueuePlayerModel(Base):
    __tablename__ = "queue_players"
    __table_args__ = (
        UniqueConstraint("queue_id", "player_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    queue_id: Mapped[UUID] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    team_number: Mapped[int] = mapped_column(Integer, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class MatchModel(Base):
    __tablename__ = "matches"
    __table_args__ = (
        UniqueConstraint("guild_id", "match_number"),
        UniqueConstraint("queue_id"),
        Index("ix_matches_state_deadline", "state", "result_deadline_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False)
    queue_id: Mapped[UUID] = mapped_column(ForeignKey("queues.id", ondelete="RESTRICT"), nullable=False)
    match_number: Mapped[int] = mapped_column(Integer, nullable=False)
    creator_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    team1_captain_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    team2_captain_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    ruleset_key: Mapped[RulesetKey] = enum_column(RulesetKey, default=RulesetKey.APOSTADO)
    mode: Mapped[MatchMode] = enum_column(MatchMode, default=MatchMode.TWO_V_TWO)
    state: Mapped[MatchState] = enum_column(MatchState, default=MatchState.CREATED)
    result_phase: Mapped[MatchResultPhase] = enum_column(MatchResultPhase, default=MatchResultPhase.CAPTAIN)
    team_size: Mapped[int] = mapped_column(Integer, nullable=False)
    room_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    room_password: Mapped[str | None] = mapped_column(String(128), nullable=True)
    room_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    public_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    team1_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    team2_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    captain_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fallback_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    room_info_submitted_by_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    result_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    force_close_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rehost_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    live_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MatchPlayerModel(Base):
    __tablename__ = "match_players"
    __table_args__ = (
        UniqueConstraint("match_id", "player_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[UUID] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    team_number: Mapped[int] = mapped_column(Integer, nullable=False)
    result: Mapped[MatchPlayerResult] = enum_column(MatchPlayerResult, default=MatchPlayerResult.NONE)
    rating_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    coins_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_winner_mvp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_loser_mvp: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class MatchVoteModel(Base):
    __tablename__ = "match_votes"
    __table_args__ = (
        Index(
            "ix_match_votes_active_unique",
            "match_id",
            "player_id",
            unique=True,
            postgresql_where=text("superseded_at is null"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[UUID] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    winner_team_number: Mapped[int] = mapped_column(Integer, nullable=False)
    winner_mvp_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    loser_mvp_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RatingHistoryModel(Base):
    __tablename__ = "rating_history"
    __table_args__ = (
        UniqueConstraint("season_player_id", "match_id", "reason"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season_player_id: Mapped[int] = mapped_column(ForeignKey("season_players.id", ondelete="CASCADE"), nullable=False)
    match_id: Mapped[UUID | None] = mapped_column(ForeignKey("matches.id"), nullable=True)
    before_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    after_rating: Mapped[int] = mapped_column(Integer, nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[RatingReason] = enum_column(RatingReason, default=RatingReason.MATCH_RESULT)
    actor_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
