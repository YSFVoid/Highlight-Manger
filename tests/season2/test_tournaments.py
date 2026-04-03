from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService
from highlight_manager.modules.tournaments.repository import TournamentRepository
from highlight_manager.modules.tournaments.service import TournamentService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'tournaments.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_tournament_registration_blocks_duplicate_player(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    season_service = SeasonService()
    profile_service = ProfileService()
    tournament_service = TournamentService(
        economy_service=EconomyService(),
        moderation_service=ModerationService(),
    )

    guilds = GuildRepository(session)
    seasons = SeasonRepository(session)
    profiles = ProfileRepository(session)
    tournaments = TournamentRepository(session)
    moderation = ModerationRepository(session)

    bundle = await guild_service.ensure_guild(guilds, 999, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    captain_a = await profile_service.ensure_player(profiles, bundle.guild.id, 3001)
    captain_b = await profile_service.ensure_player(profiles, bundle.guild.id, 3002)
    teammate = await profile_service.ensure_player(profiles, bundle.guild.id, 3003)
    reserve_a = await profile_service.ensure_player(profiles, bundle.guild.id, 3004)
    reserve_b = await profile_service.ensure_player(profiles, bundle.guild.id, 3005)
    reserve_c = await profile_service.ensure_player(profiles, bundle.guild.id, 3006)

    tournament = await tournament_service.create_tournament(
        tournaments,
        moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        name="Spring Cup",
        team_size=3,
        max_teams=4,
    )

    await tournament_service.register_team(
        tournaments,
        tournament_id=tournament.id,
        captain_player_id=captain_a.id,
        team_name="Alpha",
        player_ids=[captain_a.id, teammate.id, reserve_a.id],
    )

    with pytest.raises(Exception):
        await tournament_service.register_team(
            tournaments,
            tournament_id=tournament.id,
            captain_player_id=captain_b.id,
            team_name="Bravo",
            player_ids=[captain_b.id, teammate.id, reserve_b.id],
        )


@pytest.mark.asyncio
async def test_start_tournament_is_idempotent_once_live(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    season_service = SeasonService()
    profile_service = ProfileService()
    tournament_service = TournamentService(
        economy_service=EconomyService(),
        moderation_service=ModerationService(),
    )

    guilds = GuildRepository(session)
    seasons = SeasonRepository(session)
    profiles = ProfileRepository(session)
    tournaments = TournamentRepository(session)
    moderation = ModerationRepository(session)

    bundle = await guild_service.ensure_guild(guilds, 1001, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    player_ids = []
    for discord_id in range(4001, 4005):
        player = await profile_service.ensure_player(profiles, bundle.guild.id, discord_id)
        player_ids.append(player.id)

    tournament = await tournament_service.create_tournament(
        tournaments,
        moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        name="Night Cup",
        team_size=2,
        max_teams=4,
    )

    await tournament_service.register_team(
        tournaments,
        tournament_id=tournament.id,
        captain_player_id=player_ids[0],
        team_name="Alpha",
        player_ids=[player_ids[0], player_ids[1]],
    )
    await tournament_service.register_team(
        tournaments,
        tournament_id=tournament.id,
        captain_player_id=player_ids[2],
        team_name="Bravo",
        player_ids=[player_ids[2], player_ids[3]],
    )

    first_start = await tournament_service.start_tournament(tournaments, tournament_id=tournament.id)
    first_matches = await tournaments.list_matches(tournament.id)
    second_start = await tournament_service.start_tournament(tournaments, tournament_id=tournament.id)
    second_matches = await tournaments.list_matches(tournament.id)

    assert first_start.state.value == "live"
    assert second_start.state.value == "live"
    assert len(first_matches) == 1
    assert len(second_matches) == 1
