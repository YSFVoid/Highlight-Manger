from __future__ import annotations

from pymongo import ReturnDocument

from highlight_manager.models.economy import CoinSpendRequest, EconomyConfig
from highlight_manager.models.enums import CoinSpendStatus
from highlight_manager.repositories.base import BaseRepository


class EconomyConfigRepository(BaseRepository[EconomyConfig]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index("guild_id", unique=True)

    async def get(self, guild_id: int) -> EconomyConfig | None:
        return self._to_model(await self.collection.find_one({"guild_id": guild_id}))

    async def upsert(self, config: EconomyConfig) -> EconomyConfig:
        updated = await self.collection.find_one_and_update(
            {"guild_id": config.guild_id},
            {"$set": config.model_dump(mode="python")},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or config


class CoinSpendRequestRepository(BaseRepository[CoinSpendRequest]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("request_number", 1)], unique=True)
        await self.collection.create_index([("guild_id", 1), ("user_id", 1), ("status", 1)])

    async def create(self, request: CoinSpendRequest) -> CoinSpendRequest:
        await self.collection.insert_one(request.model_dump(mode="python"))
        return request

    async def replace(self, request: CoinSpendRequest) -> CoinSpendRequest:
        updated = await self.collection.find_one_and_replace(
            {"guild_id": request.guild_id, "request_number": request.request_number},
            request.model_dump(mode="python"),
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or request

    async def get(self, guild_id: int, request_number: int) -> CoinSpendRequest | None:
        return self._to_model(
            await self.collection.find_one({"guild_id": guild_id, "request_number": request_number}),
        )

    async def get_latest_request(self, guild_id: int) -> CoinSpendRequest | None:
        cursor = self.collection.find({"guild_id": guild_id}).sort("request_number", -1).limit(1)
        documents = await cursor.to_list(length=1)
        return self._to_model(documents[0]) if documents else None

    async def list_for_user(self, guild_id: int, user_id: int) -> list[CoinSpendRequest]:
        cursor = self.collection.find({"guild_id": guild_id, "user_id": user_id}).sort("request_number", -1)
        return self._to_models(await cursor.to_list(length=None))

    async def list_pending(self, guild_id: int) -> list[CoinSpendRequest]:
        cursor = self.collection.find(
            {"guild_id": guild_id, "status": CoinSpendStatus.PENDING.value},
        ).sort("request_number", 1)
        return self._to_models(await cursor.to_list(length=None))
