from __future__ import annotations

from datetime import datetime

from pydantic import Field

from highlight_manager.models.base import AppModel
from highlight_manager.utils.dates import utcnow


class SeasonRecord(AppModel):
    guild_id: int
    season_number: int
    name: str
    is_active: bool = True
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None
