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
    first_assigned_rank: int | None = None
    last_assigned_rank: int | None = None
    renamed_members: int = 0
    rename_failures: int = 0
    rename_already_correct: int = 0
    rename_skipped_due_to_hierarchy: int = 0
    rename_skipped_due_to_missing_permission: int = 0
    rename_skipped_other: int = 0
    skipped_members: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
