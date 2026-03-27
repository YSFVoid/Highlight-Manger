from __future__ import annotations

from datetime import datetime

from pydantic import Field

from highlight_manager.models.base import AppModel
from highlight_manager.models.enums import (
    TournamentMatchStatus,
    TournamentPhase,
    TournamentSize,
    TournamentTeamStatus,
)
from highlight_manager.utils.dates import utcnow


class TournamentRecord(AppModel):
    guild_id: int
    tournament_number: int
    name: str
    size: TournamentSize
    phase: TournamentPhase = TournamentPhase.REGISTRATION
    registration_open: bool = True
    team_size: int = 4
    max_teams: int
    group_count: int
    advancing_per_group: int
    next_match_number: int = 1
    announcement_channel_id: int | None = None
    announcement_message_id: int | None = None
    registration_message_id: int | None = None
    champion_team_id: int | None = None
    runner_up_team_id: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    canceled_at: datetime | None = None


class TournamentTeam(AppModel):
    guild_id: int
    tournament_number: int
    team_number: int
    team_name: str
    captain_id: int
    player_ids: list[int]
    group_label: str | None = None
    status: TournamentTeamStatus = TournamentTeamStatus.ACTIVE
    participation_rewarded: bool = False
    registered_at: datetime = Field(default_factory=utcnow)


class TournamentMatchRecord(AppModel):
    guild_id: int
    tournament_number: int
    match_number: int
    phase: TournamentPhase
    round_label: str
    group_label: str | None = None
    team1_id: int
    team2_id: int
    scheduled_at: datetime | None = None
    status: TournamentMatchStatus = TournamentMatchStatus.SCHEDULED
    best_of: int = 3
    team1_room_wins: int = 0
    team2_room_wins: int = 0
    winner_team_id: int | None = None
    team1_voice_channel_id: int | None = None
    team2_voice_channel_id: int | None = None
    result_channel_id: int | None = None
    result_message_id: int | None = None
    reminder_sent_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
