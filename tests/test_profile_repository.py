from datetime import UTC, datetime

import pytest

from highlight_manager.models.profile import PlayerProfile
from highlight_manager.repositories.profile_repository import ProfileRepository


class FakeCollection:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []

    async def update_many(self, query: dict, update: dict) -> None:
        self.calls.append((query, update))


@pytest.mark.asyncio
async def test_reset_for_new_season_resets_everyone_to_zero_points_and_rank_one() -> None:
    collection = FakeCollection()
    repository = ProfileRepository(collection, PlayerProfile)

    await repository.reset_for_new_season(123, datetime.now(UTC))

    assert collection.calls[0][0] == {"guild_id": 123}
    assert collection.calls[0][1]["$set"]["current_points"] == 0
    assert collection.calls[0][1]["$set"]["current_rank"] == 1
    assert len(collection.calls) == 1
