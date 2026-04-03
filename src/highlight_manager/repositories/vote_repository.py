from __future__ import annotations

from pymongo import ReturnDocument

from highlight_manager.models.vote import MatchVote
from highlight_manager.repositories.base import BaseRepository


class VoteRepository(BaseRepository[MatchVote]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("match_number", 1), ("user_id", 1)], unique=True)

    async def upsert(self, vote: MatchVote) -> MatchVote:
        updated = await self.collection.find_one_and_update(
            {"guild_id": vote.guild_id, "match_number": vote.match_number, "user_id": vote.user_id},
            {"$set": vote.model_dump(mode="python")},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or vote

    async def list_for_match(self, guild_id: int, match_number: int) -> list[MatchVote]:
        cursor = self.collection.find({"guild_id": guild_id, "match_number": match_number})
        return self._to_models(await cursor.to_list(length=None))

    async def delete_for_match(self, guild_id: int, match_number: int) -> None:
        await self.collection.delete_many({"guild_id": guild_id, "match_number": match_number})
