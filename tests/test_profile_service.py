from datetime import UTC, datetime, timedelta

import pytest

from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType, ResultSource
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.services.profile_service import ProfileService
from highlight_manager.services.rank_service import RankService, RankSyncResult
from highlight_manager.utils.dates import minutes_from_now, utcnow


class FakeProfileRepository:
    def __init__(self) -> None:
        self.storage: dict[tuple[int, int], PlayerProfile] = {}

    async def get(self, guild_id: int, user_id: int) -> PlayerProfile | None:
        return self.storage.get((guild_id, user_id))

    async def upsert(self, profile: PlayerProfile) -> PlayerProfile:
        self.storage[(profile.guild_id, profile.user_id)] = profile
        return profile

    async def reset_for_new_season(self, guild_id: int, updated_at) -> None:
        return None

    async def list_for_ranking(self, guild_id: int) -> list[PlayerProfile]:
        return [profile for (stored_guild_id, _), profile in self.storage.items() if stored_guild_id == guild_id]

    async def count_for_guild(self, guild_id: int) -> int:
        return sum(1 for stored_guild_id, _ in self.storage if stored_guild_id == guild_id)

    async def list_leaderboard(self, guild_id: int, limit: int = 10) -> list[PlayerProfile]:
        profiles = await self.list_for_ranking(guild_id)
        ranked = RankService().sort_profiles_for_ranking(profiles)
        return ranked[:limit]


class FakeMember:
    def __init__(self, user_id: int, *, joined_at=None) -> None:
        self.id = user_id
        self.joined_at = joined_at or datetime.now(UTC)
        self.bot = False
        self.guild = None


class QuietRankService(RankService):
    async def sync_member_rank(self, member, profile, config) -> RankSyncResult:
        return RankSyncResult(nickname_attempted=True)


class FakeGuild:
    def __init__(self, guild_id: int, members: dict[int, FakeMember] | None = None) -> None:
        self.id = guild_id
        self._members = members or {}

    def get_member(self, user_id: int):
        return self._members.get(user_id)

    @property
    def members(self):
        return list(self._members.values())


@pytest.mark.asyncio
async def test_apply_match_outcome_updates_points_and_recalculates_positions() -> None:
    repository = FakeProfileRepository()
    service = ProfileService(repository, QuietRankService())
    now = datetime.now(UTC)
    guild = FakeGuild(
        1,
        members={
            10: FakeMember(10, joined_at=now - timedelta(days=20)),
            20: FakeMember(20, joined_at=now - timedelta(days=10)),
        },
    )
    config = GuildConfig(guild_id=1)
    for member in guild._members.values():
        member.guild = guild
    for user_id, member in guild._members.items():
        await repository.upsert(PlayerProfile(guild_id=1, user_id=user_id, joined_at=member.joined_at))

    match = MatchRecord(
        guild_id=1,
        match_number=1,
        creator_id=10,
        mode=MatchMode.ONE_V_ONE,
        match_type=MatchType.APOSTADO,
        status=MatchStatus.VOTING,
        team1_player_ids=[10],
        team2_player_ids=[20],
        created_at=utcnow(),
        queue_expires_at=minutes_from_now(5),
        vote_expires_at=minutes_from_now(30),
    )

    summary = await service.apply_match_outcome(
        guild,
        match,
        config,
        winner_team=1,
        winner_mvp_id=None,
        loser_mvp_id=None,
        source=ResultSource.CONSENSUS,
    )

    assert summary.winner_team == 1
    assert repository.storage[(1, 10)].current_points == 10
    assert repository.storage[(1, 20)].current_points == -8
    assert repository.storage[(1, 10)].current_rank == 1
    assert repository.storage[(1, 20)].current_rank == 2


@pytest.mark.asyncio
async def test_set_points_recalculates_live_rank_positions() -> None:
    repository = FakeProfileRepository()
    service = ProfileService(repository, QuietRankService())
    now = datetime.now(UTC)
    guild = FakeGuild(
        1,
        members={
            10: FakeMember(10, joined_at=now - timedelta(days=20)),
            20: FakeMember(20, joined_at=now - timedelta(days=10)),
        },
    )
    config = GuildConfig(guild_id=1)
    for member in guild._members.values():
        member.guild = guild
    await repository.upsert(PlayerProfile(guild_id=1, user_id=10, current_points=10, current_rank=2, joined_at=guild.get_member(10).joined_at))
    await repository.upsert(PlayerProfile(guild_id=1, user_id=20, current_points=20, current_rank=1, joined_at=guild.get_member(20).joined_at))

    result = await service.set_points(guild, 10, config, 30)

    assert result.profile.current_rank == 1
    assert repository.storage[(1, 20)].current_rank == 2


@pytest.mark.asyncio
async def test_handle_member_join_assigns_last_rank_position_initially() -> None:
    repository = FakeProfileRepository()
    service = ProfileService(repository, QuietRankService())
    now = datetime.now(UTC)
    guild = FakeGuild(
        1,
        members={
            1: FakeMember(1, joined_at=now - timedelta(days=30)),
            2: FakeMember(2, joined_at=now - timedelta(days=20)),
            3: FakeMember(3, joined_at=now - timedelta(days=1)),
        },
    )
    config = GuildConfig(guild_id=1)
    for member in guild._members.values():
        member.guild = guild
    await repository.upsert(PlayerProfile(guild_id=1, user_id=1, current_rank=1, joined_at=guild.get_member(1).joined_at))
    await repository.upsert(PlayerProfile(guild_id=1, user_id=2, current_rank=2, joined_at=guild.get_member(2).joined_at))

    profile = await service.handle_member_join(guild.get_member(3), config)

    assert profile.current_rank == 3
    assert profile.current_points == 0


@pytest.mark.asyncio
async def test_handle_member_join_preserves_existing_profile_state() -> None:
    repository = FakeProfileRepository()
    service = ProfileService(repository, QuietRankService())
    now = datetime.now(UTC)
    guild = FakeGuild(
        1,
        members={
            10: FakeMember(10, joined_at=now - timedelta(days=30)),
        },
    )
    config = GuildConfig(guild_id=1)
    for member in guild._members.values():
        member.guild = guild
    await repository.upsert(
        PlayerProfile(
            guild_id=1,
            user_id=10,
            current_points=75,
            lifetime_points=120,
            current_rank=4,
            joined_at=now - timedelta(days=45),
        )
    )

    profile = await service.handle_member_join(guild.get_member(10), config)

    assert profile.current_points == 75
    assert profile.lifetime_points == 120
    assert profile.current_rank == 4
    assert profile.joined_at == now - timedelta(days=45)
