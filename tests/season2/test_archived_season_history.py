from __future__ import annotations

import inspect
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.bot import HighlightBot, PlayerCommands
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.models.competitive import SeasonPlayerModel
from highlight_manager.db.models.economy import WalletModel
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.cache import SimpleTTLCache
from highlight_manager.modules.common.enums import SeasonStatus
from highlight_manager.modules.common.exceptions import ValidationError
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.repository import RankRepository
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'archived-season-history.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


class DummyLogger:
    def warning(self, *_args, **_kwargs) -> None:
        return


class DummyAvatar:
    def __init__(self, url: str = "https://example.com/avatar.png") -> None:
        self.url = url


class DummyMember:
    def __init__(self, discord_user_id: int, display_name: str) -> None:
        self.id = discord_user_id
        self.display_name = display_name
        self.display_avatar = DummyAvatar()
        self.global_name = display_name
        self.joined_at = None


class DummyGuild:
    def __init__(self, guild_id: int, name: str = "Highlight") -> None:
        self.id = guild_id
        self.name = name

    def get_member(self, _discord_user_id: int):
        return None


class DummySessionContext:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self):
        return SimpleNamespace(
            guilds=GuildRepository(self._session),
            seasons=SeasonRepository(self._session),
            profiles=ProfileRepository(self._session),
            ranks=RankRepository(self._session),
            economy=EconomyRepository(self._session),
        )

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class DummyRuntime:
    def __init__(self, session: AsyncSession, services) -> None:
        self._session = session
        self.services = services

    def session(self) -> DummySessionContext:
        return DummySessionContext(self._session)


@dataclass(slots=True)
class ArchivedSeasonContext:
    session: AsyncSession
    settings: Settings
    guild_id: int
    guild_service: GuildService
    season_service: SeasonService
    profile_service: ProfileService
    guilds: GuildRepository
    seasons: SeasonRepository
    profiles: ProfileRepository
    ranks: RankRepository
    economy: EconomyRepository


async def _build_context(session: AsyncSession, *, discord_guild_id: int = 9901) -> ArchivedSeasonContext:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    season_service = SeasonService()
    profile_service = ProfileService()
    guilds = GuildRepository(session)
    seasons = SeasonRepository(session)
    profiles = ProfileRepository(session)
    ranks = RankRepository(session)
    economy = EconomyRepository(session)
    bundle = await guild_service.ensure_guild(guilds, discord_guild_id, "Highlight")
    await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    return ArchivedSeasonContext(
        session=session,
        settings=settings,
        guild_id=bundle.guild.id,
        guild_service=guild_service,
        season_service=season_service,
        profile_service=profile_service,
        guilds=guilds,
        seasons=seasons,
        profiles=profiles,
        ranks=ranks,
        economy=economy,
    )


def _make_bot(session: AsyncSession, settings: Settings) -> HighlightBot:
    bot = object.__new__(HighlightBot)
    bot.runtime = DummyRuntime(
        session,
        SimpleNamespace(
            guilds=GuildService(settings),
            seasons=SeasonService(),
        ),
    )
    bot.logger = DummyLogger()
    bot.leaderboard_card_cache = SimpleTTLCache(maxsize=8, ttl=60)
    bot.log_duration = lambda *_args, **_kwargs: None

    async def _fetch_avatar_bytes(_member, *, size: int = 128):
        return None

    bot.fetch_avatar_bytes = _fetch_avatar_bytes
    return bot


async def _count_wallets(session: AsyncSession) -> int:
    value = await session.scalar(select(func.count()).select_from(WalletModel))
    return int(value or 0)


@pytest.mark.asyncio
async def test_season_service_lists_and_resolves_archived_seasons(session: AsyncSession) -> None:
    context = await _build_context(session)
    active_one = await context.seasons.get_active(context.guild_id)
    assert active_one is not None
    active_two = await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        (await context.guild_service.get_bundle(context.guilds, 9901)).settings,  # type: ignore[arg-type]
    )
    active_three = await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        (await context.guild_service.get_bundle(context.guilds, 9901)).settings,  # type: ignore[arg-type]
    )

    seasons = await context.season_service.list_history(context.seasons, context.guild_id)

    assert [season.season_number for season in seasons[:3]] == [
        active_three.season_number,
        active_two.season_number,
        active_one.season_number,
    ]
    resolved = await context.season_service.resolve_archived_season(
        context.seasons,
        context.guild_id,
        active_two.season_number,
    )
    assert resolved.id == active_two.id
    assert resolved.status == SeasonStatus.ENDED
    with pytest.raises(ValidationError):
        await context.season_service.resolve_archived_season(
            context.seasons,
            context.guild_id,
            active_three.season_number,
        )


@pytest.mark.asyncio
async def test_archived_profile_response_is_read_only_for_missing_history(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9902)
    bundle = await context.guild_service.get_bundle(context.guilds, 9902)
    assert bundle is not None
    archived_season = await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        bundle.settings,
    )
    active_season = await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        bundle.settings,
    )
    assert archived_season.status == SeasonStatus.ENDED
    assert active_season.status == SeasonStatus.ACTIVE
    member = DummyMember(20_001, "Archived Player")
    await context.profile_service.ensure_player(
        context.profiles,
        context.guild_id,
        member.id,
        display_name=member.display_name,
    )
    bot = _make_bot(session, context.settings)
    before_wallets = await _count_wallets(session)
    before_season_rows = await session.scalar(select(func.count()).select_from(SeasonPlayerModel))

    embed, file = await bot.build_archived_profile_command_response(
        DummyGuild(9902),
        member,
        season_number=archived_season.season_number,
    )

    after_wallets = await _count_wallets(session)
    after_season_rows = await session.scalar(select(func.count()).select_from(SeasonPlayerModel))
    assert file is None
    assert "No ranked record was found" in (embed.description or "")
    assert before_wallets == after_wallets == 0
    assert before_season_rows == after_season_rows == 0


@pytest.mark.asyncio
async def test_archived_profile_response_shows_historical_stats_without_live_wallet_fields(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9903)
    bundle = await context.guild_service.get_bundle(context.guilds, 9903)
    assert bundle is not None
    archived_season = await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        bundle.settings,
    )
    await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        bundle.settings,
    )
    member = DummyMember(20_101, "Season Hero")
    player = await context.profile_service.ensure_player(
        context.profiles,
        context.guild_id,
        member.id,
        display_name=member.display_name,
    )
    season_player = await context.season_service.ensure_player(
        context.seasons,
        archived_season.id,
        player.id,
    )
    season_player.rating = 1420
    season_player.wins = 14
    season_player.losses = 6
    season_player.matches_played = 20
    season_player.peak_rating = 1505
    season_player.final_leaderboard_rank = 2
    await session.flush()
    bot = _make_bot(session, context.settings)

    embed, file = await bot.build_archived_profile_command_response(
        DummyGuild(9903),
        member,
        season_number=archived_season.season_number,
    )

    rendered = "\n".join([embed.title or "", embed.description or ""] + [field.name + ":" + field.value for field in embed.fields])
    compact = rendered.replace(" ", "")
    assert file is None
    assert archived_season.name in rendered
    assert "FinalPoints:**1420**" in compact
    assert "FinalPlacement:**#2**" in compact
    assert "PeakRating:**1505**" in compact
    assert "Coins" not in rendered
    assert "Inventory" not in rendered


@pytest.mark.asyncio
async def test_archived_leaderboard_response_uses_selected_season(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9904)
    bundle = await context.guild_service.get_bundle(context.guilds, 9904)
    assert bundle is not None
    archived_season = await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        bundle.settings,
    )
    await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        bundle.settings,
    )
    first_member = DummyMember(20_201, "First Seed")
    second_member = DummyMember(20_202, "Second Seed")
    first_player = await context.profile_service.ensure_player(
        context.profiles,
        context.guild_id,
        first_member.id,
        display_name=first_member.display_name,
    )
    second_player = await context.profile_service.ensure_player(
        context.profiles,
        context.guild_id,
        second_member.id,
        display_name=second_member.display_name,
    )
    first_row = await context.season_service.ensure_player(context.seasons, archived_season.id, first_player.id)
    second_row = await context.season_service.ensure_player(context.seasons, archived_season.id, second_player.id)
    first_row.rating = 1600
    first_row.wins = 16
    first_row.losses = 4
    first_row.matches_played = 20
    second_row.rating = 1400
    second_row.wins = 12
    second_row.losses = 8
    second_row.matches_played = 20
    await session.flush()
    bot = _make_bot(session, context.settings)

    embed, file = await bot.build_archived_leaderboard_command_response(
        DummyGuild(9904),
        season_number=archived_season.season_number,
    )

    assert archived_season.name in (embed.description or "")
    assert any("First Seed" in field.value for field in embed.fields)
    assert file is None or file.filename == "leaderboard-card.png"


@pytest.mark.asyncio
async def test_season_history_response_lists_current_and_archived_seasons(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9905)
    bundle = await context.guild_service.get_bundle(context.guilds, 9905)
    assert bundle is not None
    first_archived = await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        bundle.settings,
    )
    current = await context.season_service.start_next_season(
        context.seasons,
        context.guild_id,
        bundle.settings,
    )
    bot = _make_bot(session, context.settings)

    embed = await bot.build_season_history_command_response(DummyGuild(9905))

    rendered = "\n".join([embed.title or "", embed.description or ""] + [field.name + ":" + field.value for field in embed.fields])
    assert "Season History" in rendered
    assert current.name in rendered
    assert first_archived.name in rendered
    assert "`!leaderboard 1`" in rendered or "`!leaderboard" in rendered
    assert "`!profile 1`" in rendered or "`!profile" in rendered


def test_prefix_command_surface_and_help_copy_support_archived_seasons() -> None:
    profile_source = inspect.getsource(PlayerCommands.profile.callback)
    rank_source = inspect.getsource(PlayerCommands.rank.callback)
    leaderboard_source = inspect.getsource(PlayerCommands.leaderboard.callback)
    seasons_source = inspect.getsource(PlayerCommands.seasons.callback)
    archived_profile_source = inspect.getsource(HighlightBot.build_archived_profile_command_response)
    help_source = inspect.getsource(HighlightBot.build_help_embed)

    assert "season_number: Optional[int] = None" in profile_source
    assert "season_number: Optional[int] = None" in rank_source
    assert "season_number: Optional[int] = None" in leaderboard_source
    assert "build_profile_command_response" in profile_source
    assert "build_archived_profile_command_response" in profile_source
    assert "build_leaderboard_command_response" in leaderboard_source
    assert "build_archived_leaderboard_command_response" in leaderboard_source
    assert '@commands.command(name="seasons")' in seasons_source
    assert "get_player(" in archived_profile_source
    assert "ensure_player(" not in archived_profile_source
    assert "ensure_wallet" not in archived_profile_source
    assert "`{prefix}seasons` Browse season history" in help_source
    assert "`{prefix}leaderboard <season_number>`" in help_source
    assert "`{prefix}profile <season_number>`" in help_source
