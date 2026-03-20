from __future__ import annotations

from datetime import datetime

from pydantic import Field

from highlight_manager.models.base import AppModel
from highlight_manager.utils.dates import utcnow


class MatchVote(AppModel):
    guild_id: int
    match_number: int
    user_id: int
    winner_team: int
    winner_mvp_id: int | None = None
    loser_mvp_id: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
