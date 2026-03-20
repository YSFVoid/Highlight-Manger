from __future__ import annotations

from pymongo import ReturnDocument

from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.repositories.base import BaseRepository


class ConfigRepository(BaseRepository[GuildConfig]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index("guild_id", unique=True)

    async def get(self, guild_id: int) -> GuildConfig | None:
        return self._to_model(await self.collection.find_one({"guild_id": guild_id}))

    async def upsert(self, config: GuildConfig) -> GuildConfig:
        document = config.model_dump(mode="python")
        updated = await self.collection.find_one_and_update(
            {"guild_id": config.guild_id},
            {"$set": document},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or config

    async def update_fields(self, guild_id: int, updates: dict) -> GuildConfig | None:
        updated = await self.collection.find_one_and_update(
            {"guild_id": guild_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated)

    async def reserve_next_match_number(self, guild_id: int, defaults: GuildConfig) -> int:
        updated = await self.collection.find_one_and_update(
            {"guild_id": guild_id},
            {
                "$setOnInsert": defaults.model_dump(mode="python"),
                "$inc": {"next_match_number": 1},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            return 1
        return int(updated["next_match_number"]) - 1
