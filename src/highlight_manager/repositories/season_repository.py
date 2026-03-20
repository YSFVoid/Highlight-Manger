from __future__ import annotations

from pymongo import ReturnDocument

from highlight_manager.models.season import SeasonRecord
from highlight_manager.repositories.base import BaseRepository


class SeasonRepository(BaseRepository[SeasonRecord]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("season_number", 1)], unique=True)
        await self.collection.create_index([("guild_id", 1), ("is_active", 1)])

    async def get_active(self, guild_id: int) -> SeasonRecord | None:
        return self._to_model(await self.collection.find_one({"guild_id": guild_id, "is_active": True}))

    async def get_latest(self, guild_id: int) -> SeasonRecord | None:
        cursor = self.collection.find({"guild_id": guild_id}).sort("season_number", -1).limit(1)
        documents = await cursor.to_list(length=1)
        return self._to_model(documents[0]) if documents else None

    async def create(self, season: SeasonRecord) -> SeasonRecord:
        await self.collection.insert_one(season.model_dump(mode="python"))
        return season

    async def end_active(self, guild_id: int, ended_at, updates: dict | None = None) -> SeasonRecord | None:
        payload = {"is_active": False, "ended_at": ended_at}
        if updates:
            payload.update(updates)
        updated = await self.collection.find_one_and_update(
            {"guild_id": guild_id, "is_active": True},
            {"$set": payload},
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated)
