from __future__ import annotations

from datetime import datetime

from pydantic import Field

from highlight_manager.models.base import AppModel
from highlight_manager.models.enums import CoinSpendStatus
from highlight_manager.utils.dates import utcnow


class EconomyConfig(AppModel):
    guild_id: int
    match_participation: int = 5
    match_win_bonus: int = 5
    winner_mvp_bonus: int = 3
    loser_mvp_bonus: int = 2
    tournament_participation: int = 15
    tournament_runner_up: int = 25
    tournament_champion: int = 40
    next_request_number: int = 1


class CoinSpendRequest(AppModel):
    guild_id: int
    request_number: int
    user_id: int
    requested_item_text: str
    coin_amount: int
    shop_item_id: int | None = None
    status: CoinSpendStatus = CoinSpendStatus.PENDING
    created_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = None
    staff_actor_id: int | None = None
    rejection_reason: str | None = None
