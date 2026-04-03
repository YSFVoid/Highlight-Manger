from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import MatchMode, RulesetKey
from highlight_manager.modules.common.exceptions import ValidationError
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.repository import RankRepository
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'competitive.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_queue_requires_room_info_before_match_creation(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    profile_service = ProfileService()
    season_service = SeasonService()
    rank_service = RankService()
    moderation_service = ModerationService()
    economy_service = EconomyService()
    match_service = MatchService(
        settings,
        profile_service=profile_service,
        season_service=season_service,
        rank_service=rank_service,
        economy_service=economy_service,
        moderation_service=moderation_service,
    )

    guilds = GuildRepository(session)
    profiles = ProfileRepository(session)
    seasons = SeasonRepository(session)
    matches = MatchRepository(session)
    moderation = ModerationRepository(session)

    bundle = await guild_service.ensure_guild(guilds, 123, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    creator = await profile_service.ensure_player(profiles, bundle.guild.id, 1001, display_name="Creator")
    teammate = await profile_service.ensure_player(profiles, bundle.guild.id, 1002, display_name="Teammate")
    opponent_one = await profile_service.ensure_player(profiles, bundle.guild.id, 1003, display_name="Opponent1")
    opponent_two = await profile_service.ensure_player(profiles, bundle.guild.id, 1004, display_name="Opponent2")

    queue = await match_service.create_queue(
        matches,
        profiles,
        moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=creator.id,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.TWO_V_TWO,
        source_channel_id=555,
    )
    await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=teammate.id, team_number=1)
    await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=opponent_one.id, team_number=2)
    full_queue = await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=opponent_two.id, team_number=2)

    assert full_queue.queue.state.value == "full_pending_room_info"

    match = await match_service.submit_room_info(
        matches,
        profiles,
        moderation,
        queue_id=full_queue.queue.id,
        submitter_player_id=creator.id,
        is_moderator=False,
        room_code="ABC123",
        room_password="pw",
        room_notes="Final lobby",
    )

    assert match.match.queue_id == full_queue.queue.id
    assert match.match.state.value == "created"
    assert len(match.players) == 4


def test_esport_ruleset_and_mode_parsing() -> None:
    assert RulesetKey.from_input("es") == RulesetKey.ESPORT
    assert RulesetKey.from_input("esport") == RulesetKey.ESPORT
    mode = MatchMode.from_input("6v6")
    assert mode == MatchMode.SIX_V_SIX
    assert mode.team_size == 6


@pytest.mark.asyncio
async def test_confirm_match_updates_rating_and_wallets(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    profile_service = ProfileService()
    season_service = SeasonService()
    rank_service = RankService()
    moderation_service = ModerationService()
    economy_service = EconomyService()
    match_service = MatchService(
        settings,
        profile_service=profile_service,
        season_service=season_service,
        rank_service=rank_service,
        economy_service=economy_service,
        moderation_service=moderation_service,
    )

    guilds = GuildRepository(session)
    profiles = ProfileRepository(session)
    seasons = SeasonRepository(session)
    ranks = RankRepository(session)
    matches = MatchRepository(session)
    economy = EconomyRepository(session)
    moderation = ModerationRepository(session)

    bundle = await guild_service.ensure_guild(guilds, 456, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    creator = await profile_service.ensure_player(profiles, bundle.guild.id, 2001)
    teammate = await profile_service.ensure_player(profiles, bundle.guild.id, 2002)
    opponent_one = await profile_service.ensure_player(profiles, bundle.guild.id, 2003)
    opponent_two = await profile_service.ensure_player(profiles, bundle.guild.id, 2004)
    for player in [creator, teammate, opponent_one, opponent_two]:
        await season_service.ensure_player(seasons, season.id, player.id)

    queue = await match_service.create_queue(
        matches,
        profiles,
        moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=creator.id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.TWO_V_TWO,
        source_channel_id=999,
    )
    await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=teammate.id, team_number=1)
    await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=opponent_one.id, team_number=2)
    await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=opponent_two.id, team_number=2)
    match = await match_service.submit_room_info(
        matches,
        profiles,
        moderation,
        queue_id=queue.queue.id,
        submitter_player_id=creator.id,
        is_moderator=False,
        room_code="ROOM",
        room_password="PW-01",
        room_notes=None,
    )
    match = await match_service.mark_match_live(
        matches,
        match_id=match.match.id,
        result_channel_id=1,
        result_message_id=2,
        team1_voice_channel_id=3,
        team2_voice_channel_id=4,
    )

    confirmed = await match_service.confirm_match(
        matches,
        profiles,
        seasons,
        ranks,
        economy,
        moderation,
        match_id=match.match.id,
        winner_team_number=1,
        winner_mvp_player_id=creator.id,
        loser_mvp_player_id=opponent_one.id,
        actor_player_id=creator.id,
    )

    assert confirmed.match.state.value == "confirmed"
    assert any(row.rating_delta != 0 for row in confirmed.players)
    creator_wallet = await economy.ensure_wallet(creator.id)
    opponent_wallet = await economy.ensure_wallet(opponent_one.id)
    assert creator_wallet.balance == 13
    assert opponent_wallet.balance == 7


@pytest.mark.asyncio
async def test_confirm_match_rejects_invalid_mvp_team(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    profile_service = ProfileService()
    season_service = SeasonService()
    rank_service = RankService()
    moderation_service = ModerationService()
    economy_service = EconomyService()
    match_service = MatchService(
        settings,
        profile_service=profile_service,
        season_service=season_service,
        rank_service=rank_service,
        economy_service=economy_service,
        moderation_service=moderation_service,
    )

    guilds = GuildRepository(session)
    profiles = ProfileRepository(session)
    seasons = SeasonRepository(session)
    ranks = RankRepository(session)
    matches = MatchRepository(session)
    economy = EconomyRepository(session)
    moderation = ModerationRepository(session)

    bundle = await guild_service.ensure_guild(guilds, 777, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    creator = await profile_service.ensure_player(profiles, bundle.guild.id, 7001)
    teammate = await profile_service.ensure_player(profiles, bundle.guild.id, 7002)
    opponent_one = await profile_service.ensure_player(profiles, bundle.guild.id, 7003)
    opponent_two = await profile_service.ensure_player(profiles, bundle.guild.id, 7004)
    for player in [creator, teammate, opponent_one, opponent_two]:
        await season_service.ensure_player(seasons, season.id, player.id)

    queue = await match_service.create_queue(
        matches,
        profiles,
        moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=creator.id,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.TWO_V_TWO,
        source_channel_id=1000,
    )
    await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=teammate.id, team_number=1)
    await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=opponent_one.id, team_number=2)
    await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=opponent_two.id, team_number=2)
    match = await match_service.submit_room_info(
        matches,
        profiles,
        moderation,
        queue_id=queue.queue.id,
        submitter_player_id=creator.id,
        is_moderator=False,
        room_code="ROOM",
        room_password="PW-02",
        room_notes=None,
    )
    match = await match_service.mark_match_live(
        matches,
        match_id=match.match.id,
        result_channel_id=1,
        result_message_id=2,
        team1_voice_channel_id=3,
        team2_voice_channel_id=4,
    )

    with pytest.raises(ValidationError):
        await match_service.confirm_match(
            matches,
            profiles,
            seasons,
            ranks,
            economy,
            moderation,
            match_id=match.match.id,
            winner_team_number=1,
            winner_mvp_player_id=opponent_one.id,
            loser_mvp_player_id=creator.id,
            actor_player_id=creator.id,
        )


@pytest.mark.asyncio
async def test_creator_cancel_only_works_before_any_votes(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    profile_service = ProfileService()
    season_service = SeasonService()
    rank_service = RankService()
    moderation_service = ModerationService()
    economy_service = EconomyService()
    match_service = MatchService(
        settings,
        profile_service=profile_service,
        season_service=season_service,
        rank_service=rank_service,
        economy_service=economy_service,
        moderation_service=moderation_service,
    )

    guilds = GuildRepository(session)
    profiles = ProfileRepository(session)
    seasons = SeasonRepository(session)
    matches = MatchRepository(session)
    moderation = ModerationRepository(session)

    bundle = await guild_service.ensure_guild(guilds, 778, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    creator = await profile_service.ensure_player(profiles, bundle.guild.id, 7801)
    opponent = await profile_service.ensure_player(profiles, bundle.guild.id, 7802)
    for player in [creator, opponent]:
        await season_service.ensure_player(seasons, season.id, player.id)

    queue = await match_service.create_queue(
        matches,
        profiles,
        moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=creator.id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=1001,
    )
    await match_service.join_queue(matches, profiles, moderation, queue_id=queue.queue.id, player_id=opponent.id, team_number=2)
    match = await match_service.submit_room_info(
        matches,
        profiles,
        moderation,
        queue_id=queue.queue.id,
        submitter_player_id=creator.id,
        is_moderator=False,
        room_code="ROOM-CANCEL",
        room_password="PW-CANCEL",
        room_notes=None,
    )
    match = await match_service.mark_match_live(
        matches,
        match_id=match.match.id,
        result_channel_id=11,
        result_message_id=12,
        team1_voice_channel_id=13,
        team2_voice_channel_id=14,
    )

    cancelled = await match_service.cancel_match_by_creator(
        matches,
        profiles,
        moderation,
        match_id=match.match.id,
        creator_player_id=creator.id,
    )

    assert cancelled.match.state.value == "cancelled"

    second_queue = await match_service.create_queue(
        matches,
        profiles,
        moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=creator.id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=1002,
    )
    await match_service.join_queue(matches, profiles, moderation, queue_id=second_queue.queue.id, player_id=opponent.id, team_number=2)
    second_match = await match_service.submit_room_info(
        matches,
        profiles,
        moderation,
        queue_id=second_queue.queue.id,
        submitter_player_id=creator.id,
        is_moderator=False,
        room_code="ROOM-VOTED",
        room_password="PW-VOTED",
        room_notes=None,
    )
    second_match = await match_service.mark_match_live(
        matches,
        match_id=second_match.match.id,
        result_channel_id=21,
        result_message_id=22,
        team1_voice_channel_id=23,
        team2_voice_channel_id=24,
    )
    await match_service.submit_vote(
        matches,
        match_id=second_match.match.id,
        player_id=creator.id,
        winner_team_number=1,
        winner_mvp_player_id=None,
        loser_mvp_player_id=None,
    )

    with pytest.raises(ValidationError):
        await match_service.cancel_match_by_creator(
            matches,
            profiles,
            moderation,
            match_id=second_match.match.id,
            creator_player_id=creator.id,
        )
