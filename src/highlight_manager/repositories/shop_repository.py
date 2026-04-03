from __future__ import annotations

from pymongo import ReturnDocument

from highlight_manager.models.shop import ShopConfig, ShopItem
from highlight_manager.repositories.base import BaseRepository


class ShopConfigRepository(BaseRepository[ShopConfig]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index("guild_id", unique=True)

    async def get(self, guild_id: int) -> ShopConfig | None:
        return self._to_model(await self.collection.find_one({"guild_id": guild_id}))

    async def upsert(self, config: ShopConfig) -> ShopConfig:
        updated = await self.collection.find_one_and_update(
            {"guild_id": config.guild_id},
            {"$set": config.model_dump(mode="python")},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or config


class ShopItemRepository(BaseRepository[ShopItem]):
    async def ensure_indexes(self) -> None:
        await self.collection.create_index([("guild_id", 1), ("item_id", 1)], unique=True)
        await self.collection.create_index([("guild_id", 1), ("section", 1), ("active", 1)])

    async def create(self, item: ShopItem) -> ShopItem:
        await self.collection.insert_one(item.model_dump(mode="python"))
        return item

    async def replace(self, item: ShopItem) -> ShopItem:
        updated = await self.collection.find_one_and_replace(
            {"guild_id": item.guild_id, "item_id": item.item_id},
            item.model_dump(mode="python"),
            return_document=ReturnDocument.AFTER,
        )
        return self._to_model(updated) or item

    async def get(self, guild_id: int, item_id: int) -> ShopItem | None:
        return self._to_model(await self.collection.find_one({"guild_id": guild_id, "item_id": item_id}))

    async def list_for_section(self, guild_id: int, section: str, *, active_only: bool = True) -> list[ShopItem]:
        query: dict = {"guild_id": guild_id, "section": section}
        if active_only:
            query["active"] = True
        cursor = self.collection.find(query).sort([("display_order", 1), ("item_id", 1)])
        return self._to_models(await cursor.to_list(length=None))

    async def list_coin_items(self, guild_id: int) -> list[ShopItem]:
        cursor = self.collection.find(
            {"guild_id": guild_id, "active": True, "coin_price": {"$ne": None}},
        ).sort([("section", 1), ("display_order", 1), ("item_id", 1)])
        return self._to_models(await cursor.to_list(length=None))

    async def get_latest_item(self, guild_id: int) -> ShopItem | None:
        cursor = self.collection.find({"guild_id": guild_id}).sort("item_id", -1).limit(1)
        documents = await cursor.to_list(length=1)
        return self._to_model(documents[0]) if documents else None
