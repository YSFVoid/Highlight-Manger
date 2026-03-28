from __future__ import annotations

import pytest

from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.services.profile_service import IdentitySyncBatchResult, ProfileService
from highlight_manager.services.rank_service import RankSyncResult


class FakeProfileRepository:
    def __init__(self) -> None:
        self.storage: dict[tuple[int, int], PlayerProfile] = {}

    async def get(self, guild_id: int, user_id: int) -> PlayerProfile | None:
        return self.storage.get((guild_id, user_id))

    async def upsert(self, profile: PlayerProfile) -> PlayerProfile:
        self.storage[(profile.guild_id, profile.user_id)] = profile
        return profile


class FakeRankService:
    def __init__(self) -> None:
        self.calls = 0

    def resolve_rank(self, points: int, thresholds) -> int:
        return 1

    async def sync_member_roles(self, member, profile, config) -> RankSyncResult:
        self.calls += 1
        if member.id == 10:
            return RankSyncResult(role_updated=True, nickname_updated=True)
        if member.id == 20:
            return RankSyncResult(nickname_failed=True, skipped_reason="hierarchy")
        return RankSyncResult(skipped_reason="no change")


class FakeMember:
    def __init__(self, user_id: int, *, bot: bool = False) -> None:
        self.id = user_id
        self.bot = bot
        self.guild = None


class FakeGuild:
    def __init__(self, members) -> None:
        self.id = 1
        self.members = members

    def get_member(self, user_id: int):
        for member in self.members:
            if member.id == user_id:
                return member
        return None


@pytest.mark.asyncio
async def test_sync_all_member_identities_counts_results() -> None:
    repository = FakeProfileRepository()
    rank_service = FakeRankService()
    service = ProfileService(repository, rank_service)  # type: ignore[arg-type]
    guild = FakeGuild([FakeMember(10), FakeMember(20), FakeMember(30), FakeMember(40, bot=True)])
    for member in guild.members:
        member.guild = guild

    result = await service.sync_all_member_identities(guild, GuildConfig(guild_id=1))  # type: ignore[arg-type]

    assert result == IdentitySyncBatchResult(
        processed_members=3,
        role_updates=1,
        nickname_updates=1,
        nickname_failures=1,
        skipped_members=2,
    )
