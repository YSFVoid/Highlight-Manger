from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from highlight_manager.models.base import AppModel
from highlight_manager.models.enums import AuditAction
from highlight_manager.utils.dates import utcnow


class AuditLogRecord(AppModel):
    guild_id: int
    action: AuditAction
    actor_id: int | None = None
    target_id: int | None = None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
