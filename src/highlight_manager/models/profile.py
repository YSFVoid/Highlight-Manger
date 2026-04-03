from __future__ import annotations

from datetime import datetime

from pydantic import Field

from highlight_manager.models.base import AppModel
from highlight_manager.models.common import PlayerStats
from highlight_manager.utils.dates import utcnow


class PlayerProfile(AppModel):
    guild_id: int
    user_id: int
    server_joined_at: datetime | None = None
    current_points: int = 0
    lifetime_points: int = 0
    coins_balance: int = 0
    lifetime_coins_earned: int = 0
    lifetime_coins_spent: int = 0
    current_rank: int = 1
    rank0: bool = False
    blacklisted: bool = False
    season_stats: PlayerStats = Field(default_factory=PlayerStats)
    lifetime_stats: PlayerStats = Field(default_factory=PlayerStats)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
