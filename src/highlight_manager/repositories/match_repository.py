from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from pymongo import ReturnDocument

from highlight_manager.models.enums import MatchStatus
from highlight_manager.models.match import MatchRecord
from highlight_manager.repositories.base import BaseRepository


class MatchRepository(BaseRepository[MatchRecord]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("match_number", 1)], unique=True)
        await self.collection.create_index([("guild_id", 1), ("status", 1)])
        await self.collection.create_index([("queue_expires_at", 1)])
        await self.collection.create_index([("vote_expires_at", 1)])
        await self.collection.create_index([("result_channel_cleanup_at", 1)])
        await self.collection.create_index([("public_message_id", 1)])
        await self.collection.create_index([("result_channel_id", 1)])

    async def create(self, match: MatchRecord) -> MatchRecord:
        await self.collection.insert_one(match.model_dump(mode="python"))
        return match

    async def get(self, guild_id: int, match_number: int) -> MatchRecord | None:
        return self._to_model(await self.collection.find_one({"guild_id": guild_id, "match_number": match_number}))

    async def set_fields(self, guild_id: int, match_number: int, updates: dict) -> MatchRecord | None:
        updated = await self.collection.find_one_and_update(
            {"guild_id": guild_id, "match_number": match_number},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated)

    async def replace(self, match: MatchRecord) -> MatchRecord:
        updated = await self.collection.find_one_and_replace(
            {"guild_id": match.guild_id, "match_number": match.match_number},
            match.model_dump(mode="python"),
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or match

    async def delete(self, guild_id: int, match_number: int) -> bool:
        result = await self.collection.delete_one({"guild_id": guild_id, "match_number": match_number})
        return result.deleted_count > 0

    async def list_active(
        self,
        guild_id: int | None = None,
        statuses: Sequence[MatchStatus] | None = None,
    ) -> list[MatchRecord]:
        query: dict = {}
        if guild_id is not None:
            query["guild_id"] = guild_id
        if statuses:
            query["status"] = {"$in": [status.value for status in statuses]}
        cursor = self.collection.find(query).sort("created_at", 1)
        return self._to_models(await cursor.to_list(length=None))

    async def list_due_queue_expirations(self, now: datetime) -> list[MatchRecord]:
        cursor = self.collection.find(
            {
                "status": MatchStatus.OPEN.value,
                "queue_expires_at": {"$lte": now},
            },
        )
        return self._to_models(await cursor.to_list(length=None))

    async def list_due_vote_expirations(self, now: datetime) -> list[MatchRecord]:
        cursor = self.collection.find(
            {
                "status": {"$in": [MatchStatus.IN_PROGRESS.value, MatchStatus.VOTING.value, MatchStatus.FULL.value]},
                "vote_expires_at": {"$lte": now},
                "penalties_applied": False,
            },
        )
        return self._to_models(await cursor.to_list(length=None))

    async def list_due_result_cleanup(self, now: datetime) -> list[MatchRecord]:
        cursor = self.collection.find(
            {
                "status": {"$in": [MatchStatus.FINALIZED.value, MatchStatus.CANCELED.value, MatchStatus.EXPIRED.value]},
                "result_channel_id": {"$ne": None},
                "result_channel_cleanup_at": {"$lte": now},
            },
        )
        return self._to_models(await cursor.to_list(length=None))

    async def find_open_matches_for_player(self, guild_id: int, user_id: int) -> list[MatchRecord]:
        cursor = self.collection.find(
            {
                "guild_id": guild_id,
                "status": MatchStatus.OPEN.value,
                "$or": [
                    {"team1_player_ids": user_id},
                    {"team2_player_ids": user_id},
                ],
            },
        )
        return self._to_models(await cursor.to_list(length=None))

    async def get_by_public_message(self, message_id: int) -> MatchRecord | None:
        return self._to_model(await self.collection.find_one({"public_message_id": message_id}))

    async def list_closed_with_voice_channels(self) -> list[MatchRecord]:
        cursor = self.collection.find(
            {
                "status": {
                    "$in": [
                        MatchStatus.FINALIZED.value,
                        MatchStatus.CANCELED.value,
                        MatchStatus.EXPIRED.value,
                    ],
                },
                "$or": [
                    {"team1_voice_channel_id": {"$ne": None}},
                    {"team2_voice_channel_id": {"$ne": None}},
                ],
            },
        )
        return self._to_models(await cursor.to_list(length=None))
