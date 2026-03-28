from __future__ import annotations

import pytest
from pymongo import ReturnDocument

from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.repositories.config_repository import ConfigRepository


class FakeCollection:
    def __init__(self, previous_document: dict | None = None) -> None:
        self.previous_document = previous_document
        self.last_filter = None
        self.last_update = None
        self.last_upsert = None
        self.last_return_document = None

    async def find_one_and_update(self, filter_doc, update_doc, *, upsert, return_document):
        self.last_filter = filter_doc
        self.last_update = update_doc
        self.last_upsert = upsert
        self.last_return_document = return_document
        return self.previous_document


@pytest.mark.asyncio
async def test_reserve_next_match_number_uses_atomic_increment_without_conflicting_insert_fields() -> None:
    collection = FakeCollection(previous_document={"guild_id": 1, "next_match_number": 7})
    repository = ConfigRepository(collection, GuildConfig)
    defaults = GuildConfig(guild_id=1, next_match_number=1)

    match_number = await repository.reserve_next_match_number(1, defaults)

    assert match_number == 7
    assert collection.last_filter == {"guild_id": 1}
    assert collection.last_upsert is True
    assert collection.last_return_document == ReturnDocument.BEFORE
    set_stage = collection.last_update[0]["$set"]
    assert set_stage["next_match_number"] == {"$add": [{"$ifNull": ["$next_match_number", 1]}, 1]}
    assert set_stage["guild_id"] == {"$ifNull": ["$guild_id", 1]}


@pytest.mark.asyncio
async def test_reserve_next_match_number_returns_one_for_first_match() -> None:
    collection = FakeCollection(previous_document=None)
    repository = ConfigRepository(collection, GuildConfig)

    match_number = await repository.reserve_next_match_number(1, GuildConfig(guild_id=1))

    assert match_number == 1
