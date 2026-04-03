from __future__ import annotations

from datetime import datetime

from pydantic import Field

from highlight_manager.models.base import AppModel


class PlayerStats(AppModel):
    matches_played: int = 0
    wins: int = 0
    losses: int = 0
    mvp_wins: int = 0
    mvp_losses: int = 0


class PointRule(AppModel):
    winner: int
    loser: int
    winner_mvp: int | None = None
    loser_mvp: int | None = None


class RankThreshold(AppModel):
    rank: int
    min_points: int | None = None
    max_points: int | None = None


class BootstrapThreshold(AppModel):
    minimum_days: int
    rank: int
    starting_points: int


class PlayerPointDelta(AppModel):
    user_id: int
    previous_points: int
    delta: int
    new_points: int
    rank_before: int
    rank_after: int


class MatchResultSummary(AppModel):
    winner_team: int | None = None
    winner_player_ids: list[int] = Field(default_factory=list)
    loser_player_ids: list[int] = Field(default_factory=list)
    winner_mvp_id: int | None = None
    loser_mvp_id: int | None = None
    source: str
    point_deltas: list[PlayerPointDelta] = Field(default_factory=list)
    notes: str | None = None
    finalized_at: datetime


class BootstrapSummary(AppModel):
    processed_members: int = 0
    rank_counts: dict[str, int] = Field(default_factory=dict)
    rename_successes: int = 0
    rename_failures: int = 0
    skipped_members: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
