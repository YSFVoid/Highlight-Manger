from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from highlight_manager.models.base import AppModel
from highlight_manager.models.common import MatchResultSummary
from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType


class MatchRecord(AppModel):
    guild_id: int
    match_number: int
    creator_id: int
    mode: MatchMode
    match_type: MatchType
    status: MatchStatus
    team1_player_ids: list[int] = Field(default_factory=list)
    team2_player_ids: list[int] = Field(default_factory=list)
    waiting_voice_channel_id: int | None = None
    team1_voice_channel_id: int | None = None
    team2_voice_channel_id: int | None = None
    result_channel_id: int | None = None
    public_message_id: int | None = None
    source_channel_id: int | None = None
    created_at: datetime
    queue_expires_at: datetime | None = None
    vote_expires_at: datetime | None = None
    finalized_at: datetime | None = None
    canceled_at: datetime | None = None
    result_channel_cleanup_at: datetime | None = None
    penalties_applied: bool = False
    needs_admin_review: bool = False
    coin_rewards_applied: bool = False
    season_id: int | None = None
    result_summary: MatchResultSummary | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def display_id(self) -> str:
        return f"{self.match_number:03d}"

    @property
    def team_size(self) -> int:
        return self.mode.team_size

    @property
    def total_slots(self) -> int:
        return self.team_size * 2

    @property
    def is_full(self) -> bool:
        return len(self.team1_player_ids) == self.team_size and len(self.team2_player_ids) == self.team_size

    @property
    def all_player_ids(self) -> list[int]:
        return [*self.team1_player_ids, *self.team2_player_ids]
