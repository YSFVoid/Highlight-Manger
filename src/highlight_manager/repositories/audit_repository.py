from __future__ import annotations

from highlight_manager.models.audit_log import AuditLogRecord
from highlight_manager.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditLogRecord]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("created_at", -1)])
        await self.collection.create_index([("action", 1)])

    async def create(self, record: AuditLogRecord) -> AuditLogRecord:
        await self.collection.insert_one(record.model_dump(mode="python"))
        return record
