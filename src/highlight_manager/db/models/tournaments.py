from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from highlight_manager.db.base import Base
from highlight_manager.db.models._helpers import enum_column
from highlight_manager.modules.common.enums import (
    TournamentFormat,
    TournamentMatchState,
    TournamentState,
    TournamentTeamStatus,
)
from highlight_manager.modules.common.time import utcnow


class TournamentModel(Base):
    __tablename__ = "tournaments"
    __table_args__ = (
        UniqueConstraint("guild_id", "tournament_number"),
        Index("ix_tournaments_state_dates", "state", "registration_closes_at", "check_in_closes_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), nullable=False)
    tournament_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    format: Mapped[TournamentFormat] = enum_column(
        TournamentFormat,
        default=TournamentFormat.SINGLE_ELIMINATION,
    )
    state: Mapped[TournamentState] = enum_column(TournamentState, default=TournamentState.DRAFT)
    team_size: Mapped[int] = mapped_column(Integer, nullable=False)
    max_teams: Mapped[int] = mapped_column(Integer, nullable=False)
    registration_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_in_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    winner_team_id: Mapped[UUID | None] = mapped_column(nullable=True)
    runner_up_team_id: Mapped[UUID | None] = mapped_column(nullable=True)
    prize_coins_first: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prize_coins_second: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TournamentTeamModel(Base):
    __tablename__ = "tournament_teams"
    __table_args__ = (
        UniqueConstraint("tournament_id", "team_name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False)
    team_name: Mapped[str] = mapped_column(String(120), nullable=False)
    captain_player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[TournamentTeamStatus] = enum_column(
        TournamentTeamStatus,
        default=TournamentTeamStatus.REGISTERED,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class TournamentRegistrationModel(Base):
    __tablename__ = "tournament_registrations"
    __table_args__ = (
        UniqueConstraint("tournament_id", "player_id"),
        UniqueConstraint("tournament_team_id", "player_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False)
    tournament_team_id: Mapped[UUID] = mapped_column(ForeignKey("tournament_teams.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class TournamentMatchModel(Base):
    __tablename__ = "tournament_matches"
    __table_args__ = (
        UniqueConstraint("tournament_id", "round_number", "bracket_position"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tournament_id: Mapped[UUID] = mapped_column(ForeignKey("tournaments.id", ondelete="CASCADE"), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    bracket_position: Mapped[int] = mapped_column(Integer, nullable=False)
    team1_id: Mapped[UUID | None] = mapped_column(ForeignKey("tournament_teams.id"), nullable=True)
    team2_id: Mapped[UUID | None] = mapped_column(ForeignKey("tournament_teams.id"), nullable=True)
    state: Mapped[TournamentMatchState] = enum_column(
        TournamentMatchState,
        default=TournamentMatchState.SCHEDULED,
    )
    best_of: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    team1_room_wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    team2_room_wins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winner_team_id: Mapped[UUID | None] = mapped_column(ForeignKey("tournament_teams.id"), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    team1_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    team2_voice_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
