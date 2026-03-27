import pytest

from highlight_manager.models.common import MatchResultSummary
from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType, ResultSource
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.services.match_service import MatchService
from highlight_manager.utils.dates import minutes_from_now, utcnow
from highlight_manager.utils.exceptions import StateTransitionError


class FakeMatchRepository:
    def __init__(self, match: MatchRecord) -> None:
        self.match = match

    async def get(self, guild_id: int, match_number: int) -> MatchRecord | None:
        if self.match.guild_id == guild_id and self.match.match_number == match_number:
            return self.match
        return None

    async def replace(self, match: MatchRecord) -> MatchRecord:
        self.match = match
        return match


class FakeConfigService:
    def __init__(self, *, staff_ids: set[int] | None = None) -> None:
        self.staff_ids = staff_ids or set()

    async def get_or_create(self, guild_id: int) -> GuildConfig:
        return GuildConfig(guild_id=guild_id)

    async def is_staff(self, member) -> bool:
        return member.id in self.staff_ids


class FakeProfileService:
    async def apply_match_outcome(
        self,
        guild,
        match,
        config,
        *,
        winner_team,
        winner_mvp_id,
        loser_mvp_id,
        source,
        notes=None,
    ) -> MatchResultSummary:
        return MatchResultSummary(
            winner_team=winner_team,
            winner_player_ids=list(match.team1_player_ids),
            loser_player_ids=list(match.team2_player_ids),
            winner_mvp_id=winner_mvp_id,
            loser_mvp_id=loser_mvp_id,
            source=source.value,
            notes=notes,
            finalized_at=utcnow(),
        )


class FakeVoteService:
    def __init__(self, votes=None) -> None:
        self.votes = votes or []

    def validate_result_selection(self, match, *, winner_team, winner_mvp_id, loser_mvp_id) -> None:
        return None

    async def get_votes(self, match) -> list[object]:
        return list(self.votes)

    async def clear_votes(self, match) -> None:
        self.votes = []


class FakeVoiceService:
    async def cleanup_match_voices(self, guild, match) -> None:
        return None


class FakeResultChannelService:
    async def finalize_channel_behavior(self, guild, match, config) -> None:
        return None


class FakeAuditService:
    async def log(self, guild, action, message, **kwargs) -> None:
        return None


class FakeCoinsService:
    def __init__(self) -> None:
        self.calls = 0

    async def award_regular_match_rewards(self, guild, match, summary) -> None:
        self.calls += 1


class FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id

    def get_channel(self, channel_id: int | None):
        return None


class FakeMember:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.mention = f"<@{user_id}>"


@pytest.mark.asyncio
async def test_finalize_match_awards_coins_and_marks_flag() -> None:
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
    )
    coins_service = FakeCoinsService()
    service = MatchService(
        bot=None,  # type: ignore[arg-type]
        repository=FakeMatchRepository(match),
        config_service=FakeConfigService(),
        profile_service=FakeProfileService(),
        season_service=None,  # type: ignore[arg-type]
        vote_service=FakeVoteService(),
        voice_service=FakeVoiceService(),
        result_channel_service=FakeResultChannelService(),
        audit_service=FakeAuditService(),
        coins_service=coins_service,
    )

    finalized = await service.finalize_match(
        FakeGuild(1),  # type: ignore[arg-type]
        1,
        winner_team=1,
        winner_mvp_id=10,
        loser_mvp_id=20,
        source=ResultSource.CONSENSUS,
    )

    assert finalized.status == MatchStatus.FINALIZED
    assert finalized.coin_rewards_applied is True
    assert coins_service.calls == 1


@pytest.mark.asyncio
async def test_finalize_match_skips_coin_hook_if_rewards_already_applied() -> None:
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
        coin_rewards_applied=True,
    )
    coins_service = FakeCoinsService()
    service = MatchService(
        bot=None,  # type: ignore[arg-type]
        repository=FakeMatchRepository(match),
        config_service=FakeConfigService(),
        profile_service=FakeProfileService(),
        season_service=None,  # type: ignore[arg-type]
        vote_service=FakeVoteService(),
        voice_service=FakeVoiceService(),
        result_channel_service=FakeResultChannelService(),
        audit_service=FakeAuditService(),
        coins_service=coins_service,
    )

    finalized = await service.finalize_match(
        FakeGuild(1),  # type: ignore[arg-type]
        1,
        winner_team=1,
        winner_mvp_id=10,
        loser_mvp_id=20,
        source=ResultSource.FORCE_RESULT,
    )

    assert finalized.status == MatchStatus.FINALIZED
    assert coins_service.calls == 0


@pytest.mark.asyncio
async def test_creator_can_cancel_from_result_room_before_votes_start() -> None:
    match = MatchRecord(
        guild_id=1,
        match_number=1,
        creator_id=10,
        mode=MatchMode.ONE_V_ONE,
        match_type=MatchType.APOSTADO,
        status=MatchStatus.IN_PROGRESS,
        team1_player_ids=[10],
        team2_player_ids=[20],
        created_at=utcnow(),
        queue_expires_at=minutes_from_now(5),
    )
    vote_service = FakeVoteService(votes=[])
    service = MatchService(
        bot=None,  # type: ignore[arg-type]
        repository=FakeMatchRepository(match),
        config_service=FakeConfigService(),
        profile_service=FakeProfileService(),
        season_service=None,  # type: ignore[arg-type]
        vote_service=vote_service,
        voice_service=FakeVoiceService(),
        result_channel_service=FakeResultChannelService(),
        audit_service=FakeAuditService(),
        coins_service=None,
    )

    result = await service.cancel_result_room_match(FakeGuild(1), 1, FakeMember(10))  # type: ignore[arg-type]

    assert result.match.status == MatchStatus.CANCELED


@pytest.mark.asyncio
async def test_creator_cannot_cancel_from_result_room_after_votes_start() -> None:
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
    )
    vote_service = FakeVoteService(votes=[object()])
    service = MatchService(
        bot=None,  # type: ignore[arg-type]
        repository=FakeMatchRepository(match),
        config_service=FakeConfigService(),
        profile_service=FakeProfileService(),
        season_service=None,  # type: ignore[arg-type]
        vote_service=vote_service,
        voice_service=FakeVoiceService(),
        result_channel_service=FakeResultChannelService(),
        audit_service=FakeAuditService(),
        coins_service=None,
    )

    with pytest.raises(StateTransitionError):
        await service.cancel_result_room_match(FakeGuild(1), 1, FakeMember(10))  # type: ignore[arg-type]
