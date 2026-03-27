import pytest

from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType, ResultSource
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.services.profile_service import ProfileService
from highlight_manager.services.rank_service import RankService
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


class FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id

    def get_member(self, user_id: int):
        return None


@pytest.mark.asyncio
async def test_apply_match_outcome_updates_points_and_summary() -> None:
    repository = FakeProfileRepository()
    service = ProfileService(repository, RankService())
    guild = FakeGuild(1)
    config = GuildConfig(guild_id=1)
    for user_id in [10, 20]:
        await repository.upsert(PlayerProfile(guild_id=1, user_id=user_id))

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
