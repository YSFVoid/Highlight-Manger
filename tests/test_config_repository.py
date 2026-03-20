from copy import deepcopy

import pytest
from pymongo import ReturnDocument

from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.repositories.config_repository import ConfigRepository


class FakeConfigCollection:
    def __init__(self) -> None:
        self.documents: dict[int, dict] = {}

    async def create_index(self, *args, **kwargs) -> None:
        return None

    async def find_one(self, query: dict) -> dict | None:
        document = self.documents.get(query["guild_id"])
        return deepcopy(document) if document is not None else None

    async def find_one_and_update(
        self,
        query: dict,
        update: dict,
        *,
        upsert: bool = False,
        return_document=ReturnDocument.AFTER,
    ) -> dict | None:
        guild_id = query["guild_id"]
        existing = self.documents.get(guild_id)
        before = deepcopy(existing) if existing is not None else None

        if existing is None:
            if not upsert:
                return None
            existing = {"guild_id": guild_id}
            existing.update(deepcopy(update.get("$setOnInsert", {})))

        if "$set" in update:
            existing.update(deepcopy(update["$set"]))
        if "$inc" in update:
            for key, value in update["$inc"].items():
                existing[key] = int(existing.get(key, 0)) + int(value)

        self.documents[guild_id] = existing
        if return_document == ReturnDocument.BEFORE:
            return before
        return deepcopy(existing)


@pytest.mark.asyncio
async def test_reserve_next_match_number_returns_one_for_first_match() -> None:
    repository = ConfigRepository(FakeConfigCollection(), GuildConfig)

    reserved = await repository.reserve_next_match_number(123, GuildConfig(guild_id=123))

    assert reserved == 1
    assert repository.collection.documents[123]["next_match_number"] == 1


@pytest.mark.asyncio
async def test_reserve_next_match_number_returns_previous_value_for_existing_config() -> None:
    collection = FakeConfigCollection()
    collection.documents[123] = GuildConfig(guild_id=123, next_match_number=7).model_dump(mode="python")
    repository = ConfigRepository(collection, GuildConfig)

    reserved = await repository.reserve_next_match_number(123, GuildConfig(guild_id=123))

    assert reserved == 7
    assert repository.collection.documents[123]["next_match_number"] == 8
