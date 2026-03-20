from __future__ import annotations

from datetime import datetime

from pymongo import ReturnDocument

from highlight_manager.models.profile import PlayerProfile
from highlight_manager.repositories.base import BaseRepository


class ProfileRepository(BaseRepository[PlayerProfile]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("user_id", 1)], unique=True)
        await self.collection.create_index([("guild_id", 1), ("current_points", -1)])
        await self.collection.create_index([("guild_id", 1), ("blacklisted", 1)])

    async def get(self, guild_id: int, user_id: int) -> PlayerProfile | None:
        return self._to_model(await self.collection.find_one({"guild_id": guild_id, "user_id": user_id}))

    async def upsert(self, profile: PlayerProfile) -> PlayerProfile:
        updated = await self.collection.find_one_and_update(
            {"guild_id": profile.guild_id, "user_id": profile.user_id},
            {"$set": profile.model_dump(mode="python")},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or profile

    async def set_fields(self, guild_id: int, user_id: int, updates: dict) -> PlayerProfile | None:
        updated = await self.collection.find_one_and_update(
            {"guild_id": guild_id, "user_id": user_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated)

    async def list_leaderboard(self, guild_id: int, limit: int = 10) -> list[PlayerProfile]:
        cursor = self.collection.find({"guild_id": guild_id}).sort("current_points", -1).limit(limit)
        return self._to_models(await cursor.to_list(length=limit))

    async def reset_for_new_season(self, guild_id: int, updated_at: datetime) -> None:
        base_reset = {
            "current_points": 0,
            "season_stats": {
                "matches_played": 0,
                "wins": 0,
                "losses": 0,
                "mvp_wins": 0,
                "mvp_losses": 0,
            },
            "updated_at": updated_at,
        }
        await self.collection.update_many(
            {"guild_id": guild_id},
            {"$set": base_reset},
        )
        await self.collection.update_many(
            {"guild_id": guild_id, "rank0": False},
            {"$set": {"current_rank": 1}},
        )
        await self.collection.update_many(
            {"guild_id": guild_id, "rank0": True},
            {"$set": {"current_rank": 0}},
        )
