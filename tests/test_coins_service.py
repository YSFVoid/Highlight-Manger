import pytest

from highlight_manager.models.common import MatchResultSummary
from highlight_manager.models.economy import CoinSpendRequest, EconomyConfig
from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.models.tournament import TournamentTeam
from highlight_manager.services.coins_service import CoinsService
from highlight_manager.services.profile_service import ProfileService
from highlight_manager.services.rank_service import RankService
from highlight_manager.utils.dates import minutes_from_now, utcnow
from highlight_manager.utils.exceptions import UserFacingError


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


class FakeConfigService:
    async def get_or_create(self, guild_id: int):
        from highlight_manager.models.guild_config import GuildConfig

        return GuildConfig(guild_id=guild_id)


class FakeEconomyConfigRepository:
    def __init__(self) -> None:
        self.storage: dict[int, EconomyConfig] = {}

    async def get(self, guild_id: int) -> EconomyConfig | None:
        return self.storage.get(guild_id)

    async def upsert(self, config: EconomyConfig) -> EconomyConfig:
        self.storage[config.guild_id] = config
        return config


class FakeCoinSpendRequestRepository:
    def __init__(self) -> None:
        self.storage: dict[tuple[int, int], CoinSpendRequest] = {}

    async def create(self, request: CoinSpendRequest) -> CoinSpendRequest:
        self.storage[(request.guild_id, request.request_number)] = request
        return request

    async def replace(self, request: CoinSpendRequest) -> CoinSpendRequest:
        self.storage[(request.guild_id, request.request_number)] = request
        return request

    async def get(self, guild_id: int, request_number: int) -> CoinSpendRequest | None:
        return self.storage.get((guild_id, request_number))

    async def get_latest_request(self, guild_id: int) -> CoinSpendRequest | None:
        requests = [request for (stored_guild_id, _), request in self.storage.items() if stored_guild_id == guild_id]
        return max(requests, key=lambda item: item.request_number, default=None)

    async def list_pending(self, guild_id: int) -> list[CoinSpendRequest]:
        return [
            request
            for (stored_guild_id, _), request in sorted(self.storage.items())
            if stored_guild_id == guild_id and request.status.value == "PENDING"
        ]


class FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id

    def get_member(self, user_id: int):
        return None


@pytest.mark.asyncio
async def test_adjust_balance_tracks_lifetime_totals() -> None:
    profile_repository = FakeProfileRepository()
    profile_service = ProfileService(profile_repository, RankService())
    service = CoinsService(
        profile_service,
        FakeConfigService(),
        FakeEconomyConfigRepository(),
        FakeCoinSpendRequestRepository(),
    )
    guild = FakeGuild(1)

    earned = await service.adjust_balance(guild, 10, 25)
    spent = await service.adjust_balance(guild, 10, -7)

    assert earned.new_balance == 25
    assert spent.new_balance == 18
    assert profile_repository.storage[(1, 10)].lifetime_coins_earned == 25
    assert profile_repository.storage[(1, 10)].lifetime_coins_spent == 7


@pytest.mark.asyncio
async def test_create_and_approve_request_deducts_balance() -> None:
    profile_repository = FakeProfileRepository()
    profile_service = ProfileService(profile_repository, RankService())
    request_repository = FakeCoinSpendRequestRepository()
    service = CoinsService(
        profile_service,
        FakeConfigService(),
        FakeEconomyConfigRepository(),
        request_repository,
    )
    guild = FakeGuild(1)

    await service.adjust_balance(guild, 10, 40)
    request = await service.create_spend_request(guild, 10, coin_amount=20, requested_item_text="Item #1")
    approved = await service.approve_request(guild, request.request_number, 999)

    assert approved.status.value == "APPROVED"
    assert profile_repository.storage[(1, 10)].coins_balance == 20
    assert profile_repository.storage[(1, 10)].lifetime_coins_spent == 20


@pytest.mark.asyncio
async def test_create_spend_request_rejects_insufficient_balance() -> None:
    profile_repository = FakeProfileRepository()
    profile_service = ProfileService(profile_repository, RankService())
    service = CoinsService(
        profile_service,
        FakeConfigService(),
        FakeEconomyConfigRepository(),
        FakeCoinSpendRequestRepository(),
    )
    guild = FakeGuild(1)

    with pytest.raises(UserFacingError):
        await service.create_spend_request(guild, 10, coin_amount=5, requested_item_text="Not enough")


@pytest.mark.asyncio
async def test_award_regular_match_rewards_uses_default_config() -> None:
    profile_repository = FakeProfileRepository()
    profile_service = ProfileService(profile_repository, RankService())
    service = CoinsService(
        profile_service,
        FakeConfigService(),
        FakeEconomyConfigRepository(),
        FakeCoinSpendRequestRepository(),
    )
    guild = FakeGuild(1)
    match = MatchRecord(
        guild_id=1,
        match_number=1,
        creator_id=10,
        mode=MatchMode.ONE_V_ONE,
        match_type=MatchType.APOSTADO,
        status=MatchStatus.FINALIZED,
        team1_player_ids=[10],
        team2_player_ids=[20],
        created_at=utcnow(),
        queue_expires_at=minutes_from_now(5),
    )
    summary = MatchResultSummary(
        winner_team=1,
        winner_player_ids=[10],
        loser_player_ids=[20],
        winner_mvp_id=10,
        loser_mvp_id=20,
        source="CONSENSUS",
        finalized_at=utcnow(),
    )

    await service.award_regular_match_rewards(guild, match, summary)

    assert profile_repository.storage[(1, 10)].coins_balance == 13
    assert profile_repository.storage[(1, 20)].coins_balance == 7


@pytest.mark.asyncio
async def test_award_tournament_participation_is_one_time_per_team() -> None:
    profile_repository = FakeProfileRepository()
    profile_service = ProfileService(profile_repository, RankService())
    service = CoinsService(
        profile_service,
        FakeConfigService(),
        FakeEconomyConfigRepository(),
        FakeCoinSpendRequestRepository(),
    )
    guild = FakeGuild(1)
    team = TournamentTeam(
        guild_id=1,
        tournament_number=1,
        team_number=1,
        team_name="Alpha",
        captain_id=10,
        player_ids=[10, 11, 12, 13],
    )

    awarded = await service.award_tournament_participation(guild, team)
    awarded_again = await service.award_tournament_participation(guild, awarded)

    assert awarded_again.participation_rewarded is True
    assert profile_repository.storage[(1, 10)].coins_balance == 15
    assert profile_repository.storage[(1, 13)].coins_balance == 15
