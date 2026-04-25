from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import MatchMode, QueueState, RulesetKey
from highlight_manager.modules.common.exceptions import ValidationError
from highlight_manager.modules.common.time import utcnow
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'queue-ready.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class ReadyQueueContext:
    match_service: MatchService
    matches: MatchRepository
    profiles: ProfileRepository
    moderation: ModerationRepository
    queue_id: UUID
    player_ids: list[int]
    creator_id: int


async def create_ready_check_queue(session: AsyncSession, *, guild_discord_id: int) -> ReadyQueueContext:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    return await create_ready_check_queue_with_settings(session, settings=settings, guild_discord_id=guild_discord_id)


async def create_ready_check_queue_with_settings(
    session: AsyncSession,
    *,
    settings: Settings,
    guild_discord_id: int,
) -> ReadyQueueContext:
    guild_service = GuildService(settings)
    profile_service = ProfileService()
    season_service = SeasonService()
    match_service = MatchService(
        settings,
        profile_service=profile_service,
        season_service=season_service,
        rank_service=RankService(),
        economy_service=EconomyService(),
        moderation_service=ModerationService(),
    )

    guilds = GuildRepository(session)
    profiles = ProfileRepository(session)
    seasons = SeasonRepository(session)
    matches = MatchRepository(session)
    moderation = ModerationRepository(session)

    bundle = await guild_service.ensure_guild(guilds, guild_discord_id, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    players = [
        await profile_service.ensure_player(
            profiles,
            bundle.guild.id,
            guild_discord_id * 10 + index,
            display_name=f"Player {index}",
        )
        for index in range(1, 5)
    ]

    queue = await match_service.create_queue(
        matches,
        profiles,
        moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=players[0].id,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.TWO_V_TWO,
        source_channel_id=555,
    )
    await match_service.join_queue(
        matches,
        profiles,
        moderation,
        queue_id=queue.queue.id,
        player_id=players[1].id,
        team_number=1,
    )
    await match_service.join_queue(
        matches,
        profiles,
        moderation,
        queue_id=queue.queue.id,
        player_id=players[2].id,
        team_number=2,
    )
    full_queue = await match_service.join_queue(
        matches,
        profiles,
        moderation,
        queue_id=queue.queue.id,
        player_id=players[3].id,
        team_number=2,
    )
    assert full_queue.queue.state == QueueState.READY_CHECK
    return ReadyQueueContext(
        match_service=match_service,
        matches=matches,
        profiles=profiles,
        moderation=moderation,
        queue_id=full_queue.queue.id,
        player_ids=[player.id for player in players],
        creator_id=players[0].id,
    )


@pytest.mark.asyncio
async def test_ready_check_state_starts_empty_after_queue_fills(session: AsyncSession) -> None:
    context = await create_ready_check_queue(session, guild_discord_id=9001)

    snapshot = await context.matches.get_queue_snapshot(context.queue_id)

    assert snapshot is not None
    assert snapshot.queue.state == QueueState.READY_CHECK
    assert snapshot.queue.room_info_deadline_at is not None
    assert snapshot.queue.room_info_reminder_sent_at is None
    assert snapshot.ready_player_ids == set()
    assert all(row.ready_at is None for row in snapshot.players)


@pytest.mark.asyncio
async def test_ready_state_survives_snapshot_refetch(session: AsyncSession) -> None:
    context = await create_ready_check_queue(session, guild_discord_id=9002)

    await context.match_service.mark_ready(
        context.matches,
        context.profiles,
        queue_id=context.queue_id,
        player_id=context.creator_id,
    )
    refetched = await context.matches.get_queue_snapshot(context.queue_id)

    assert refetched is not None
    assert refetched.ready_player_ids == {context.creator_id}
    ready_row = next(row for row in refetched.players if row.player_id == context.creator_id)
    assert ready_row.ready_at is not None


@pytest.mark.asyncio
async def test_duplicate_ready_uses_persisted_state(session: AsyncSession) -> None:
    context = await create_ready_check_queue(session, guild_discord_id=9003)

    await context.match_service.mark_ready(
        context.matches,
        context.profiles,
        queue_id=context.queue_id,
        player_id=context.creator_id,
    )

    with pytest.raises(ValidationError):
        await context.match_service.mark_ready(
            context.matches,
            context.profiles,
            queue_id=context.queue_id,
            player_id=context.creator_id,
        )


@pytest.mark.asyncio
async def test_all_ready_moves_queue_to_room_info(session: AsyncSession) -> None:
    settings = Settings(
        DISCORD_TOKEN="token",
        DATABASE_URL="sqlite+aiosqlite:///test.db",
        room_info_timeout_seconds=180,
    )
    context = await create_ready_check_queue_with_settings(
        session,
        settings=settings,
        guild_discord_id=9004,
    )
    before_ready = await context.matches.get_queue(context.queue_id, for_update=True)
    assert before_ready is not None
    previous_deadline = utcnow() + timedelta(seconds=5)
    before_ready.room_info_deadline_at = previous_deadline
    before_ready.room_info_reminder_sent_at = utcnow()
    await context.matches.session.flush()

    snapshot = None
    for player_id in context.player_ids:
        snapshot = await context.match_service.mark_ready(
            context.matches,
            context.profiles,
            queue_id=context.queue_id,
            player_id=player_id,
        )

    assert snapshot is not None
    assert snapshot.queue.state == QueueState.FULL_PENDING_ROOM_INFO
    assert snapshot.ready_player_ids == set(context.player_ids)
    assert snapshot.queue.room_info_deadline_at is not None
    assert snapshot.queue.room_info_deadline_at.timestamp() > previous_deadline.timestamp()
    assert snapshot.queue.room_info_reminder_sent_at is None


@pytest.mark.asyncio
async def test_leaving_ready_check_queue_clears_ready_state_when_filling(session: AsyncSession) -> None:
    context = await create_ready_check_queue(session, guild_discord_id=9005)
    creator_id, teammate_id = context.player_ids[0], context.player_ids[1]

    await context.match_service.mark_ready(
        context.matches,
        context.profiles,
        queue_id=context.queue_id,
        player_id=creator_id,
    )
    await context.match_service.mark_ready(
        context.matches,
        context.profiles,
        queue_id=context.queue_id,
        player_id=teammate_id,
    )
    queue = await context.matches.get_queue(context.queue_id, for_update=True)
    assert queue is not None
    queue.room_info_reminder_sent_at = utcnow()
    await context.matches.session.flush()

    snapshot = await context.match_service.leave_queue(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=context.queue_id,
        player_id=teammate_id,
    )
    refetched = await context.matches.get_queue_snapshot(context.queue_id)

    assert snapshot.queue.state == QueueState.FILLING
    assert snapshot.queue.room_info_deadline_at is None
    assert snapshot.queue.room_info_reminder_sent_at is None
    assert snapshot.ready_player_ids == set()
    assert refetched is not None
    assert refetched.queue.room_info_deadline_at is None
    assert refetched.queue.room_info_reminder_sent_at is None
    assert refetched.ready_player_ids == set()
    assert all(row.ready_at is None for row in refetched.players)


@pytest.mark.asyncio
async def test_host_leaving_queue_cancels_with_clear_reason(session: AsyncSession) -> None:
    context = await create_ready_check_queue(session, guild_discord_id=9006)

    snapshot = await context.match_service.leave_queue(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=context.queue_id,
        player_id=context.creator_id,
    )

    assert snapshot.queue.state == QueueState.QUEUE_CANCELLED
    assert snapshot.queue.cancel_reason == "host_left"


@pytest.mark.asyncio
async def test_player_leaving_locked_room_info_queue_cancels_with_clear_reason(session: AsyncSession) -> None:
    context = await create_ready_check_queue(session, guild_discord_id=9007)
    for player_id in context.player_ids:
        snapshot = await context.match_service.mark_ready(
            context.matches,
            context.profiles,
            queue_id=context.queue_id,
            player_id=player_id,
        )
    assert snapshot.queue.state == QueueState.FULL_PENDING_ROOM_INFO

    snapshot = await context.match_service.leave_queue(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=context.queue_id,
        player_id=context.player_ids[1],
    )

    assert snapshot.queue.state == QueueState.QUEUE_CANCELLED
    assert snapshot.queue.cancel_reason == "locked_queue_player_left"
