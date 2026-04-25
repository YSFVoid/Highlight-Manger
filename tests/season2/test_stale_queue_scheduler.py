from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import MatchMode, QueueState, RulesetKey
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
from highlight_manager.tasks.scheduler import SchedulerWorker


class NullLogger:
    def info(self, *_args, **_kwargs) -> None:
        return None

    def warning(self, *_args, **_kwargs) -> None:
        return None


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'stale-queue-scheduler.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class QueueContext:
    queue_id: UUID
    guild_id: int


def build_services(settings: Settings) -> SimpleNamespace:
    profile_service = ProfileService()
    season_service = SeasonService()
    rank_service = RankService()
    moderation_service = ModerationService()
    economy_service = EconomyService()
    return SimpleNamespace(
        guilds=GuildService(settings),
        profiles=profile_service,
        seasons=season_service,
        ranks=rank_service,
        moderation=moderation_service,
        economy=economy_service,
        matches=MatchService(
            settings,
            profile_service=profile_service,
            season_service=season_service,
            rank_service=rank_service,
            economy_service=economy_service,
            moderation_service=moderation_service,
        ),
    )


def build_repositories(session: AsyncSession) -> SimpleNamespace:
    return SimpleNamespace(
        guilds=GuildRepository(session),
        profiles=ProfileRepository(session),
        seasons=SeasonRepository(session),
        matches=MatchRepository(session),
        moderation=ModerationRepository(session),
    )


def build_fake_runtime(session: AsyncSession, services: SimpleNamespace):
    class FakeRuntime:
        def __init__(self) -> None:
            self.services = services

        @asynccontextmanager
        async def session(self):
            yield build_repositories(session)

    return FakeRuntime()


async def _build_context(session: AsyncSession, *, guild_discord_id: int) -> SimpleNamespace:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    services = build_services(settings)
    repos = build_repositories(session)
    bundle = await services.guilds.ensure_guild(repos.guilds, guild_discord_id, "Highlight")
    season = await services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
    return SimpleNamespace(
        settings=settings,
        services=services,
        repos=repos,
        guild=bundle.guild,
        season=season,
        next_discord_user_id=guild_discord_id * 10,
    )


async def _create_players(context: SimpleNamespace, count: int) -> list:
    players = []
    for index in range(count):
        discord_user_id = context.next_discord_user_id + index
        players.append(
            await context.services.profiles.ensure_player(
                context.repos.profiles,
                context.guild.id,
                discord_user_id,
                display_name=f"Player {discord_user_id}",
            )
        )
    context.next_discord_user_id += count
    return players


async def _create_open_queue(
    context: SimpleNamespace,
    *,
    created_at_offset_seconds: int,
    queue_timeout_seconds: int,
) -> QueueContext:
    await context.repos.guilds.update_settings(context.guild.id, queue_timeout_seconds=queue_timeout_seconds)
    players = await _create_players(context, 1)
    snapshot = await context.services.matches.create_queue(
        context.repos.matches,
        context.repos.profiles,
        context.repos.moderation,
        guild_id=context.guild.id,
        season_id=context.season.id,
        creator_player_id=players[0].id,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.TWO_V_TWO,
        source_channel_id=555,
    )
    await context.repos.matches.set_queue_public_message_id(snapshot.queue.id, 990000 + context.guild.id)
    queue = await context.repos.matches.get_queue(snapshot.queue.id, for_update=True)
    assert queue is not None
    queue.created_at = utcnow() + timedelta(seconds=created_at_offset_seconds)
    await context.repos.matches.session.flush()
    return QueueContext(queue_id=snapshot.queue.id, guild_id=context.guild.id)


async def _create_filling_queue(
    context: SimpleNamespace,
    *,
    created_at_offset_seconds: int,
    queue_timeout_seconds: int,
) -> QueueContext:
    await context.repos.guilds.update_settings(context.guild.id, queue_timeout_seconds=queue_timeout_seconds)
    players = await _create_players(context, 2)
    queue = await context.services.matches.create_queue(
        context.repos.matches,
        context.repos.profiles,
        context.repos.moderation,
        guild_id=context.guild.id,
        season_id=context.season.id,
        creator_player_id=players[0].id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.TWO_V_TWO,
        source_channel_id=556,
    )
    snapshot = await context.services.matches.join_queue(
        context.repos.matches,
        context.repos.profiles,
        context.repos.moderation,
        queue_id=queue.queue.id,
        player_id=players[1].id,
        team_number=2,
    )
    assert snapshot.queue.state == QueueState.FILLING
    await context.repos.matches.set_queue_public_message_id(snapshot.queue.id, 991000 + context.guild.id)
    queue_row = await context.repos.matches.get_queue(snapshot.queue.id, for_update=True)
    assert queue_row is not None
    queue_row.created_at = utcnow() + timedelta(seconds=created_at_offset_seconds)
    await context.repos.matches.session.flush()
    return QueueContext(queue_id=snapshot.queue.id, guild_id=context.guild.id)


async def _create_ready_check_queue(context: SimpleNamespace) -> QueueContext:
    players = await _create_players(context, 2)
    queue = await context.services.matches.create_queue(
        context.repos.matches,
        context.repos.profiles,
        context.repos.moderation,
        guild_id=context.guild.id,
        season_id=context.season.id,
        creator_player_id=players[0].id,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=557,
    )
    snapshot = await context.services.matches.join_queue(
        context.repos.matches,
        context.repos.profiles,
        context.repos.moderation,
        queue_id=queue.queue.id,
        player_id=players[1].id,
        team_number=2,
    )
    assert snapshot.queue.state == QueueState.READY_CHECK
    queue_row = await context.repos.matches.get_queue(snapshot.queue.id, for_update=True)
    assert queue_row is not None
    queue_row.created_at = utcnow() - timedelta(hours=1)
    queue_row.room_info_deadline_at = utcnow() + timedelta(minutes=1)
    await context.repos.matches.session.flush()
    return QueueContext(queue_id=snapshot.queue.id, guild_id=context.guild.id)


@pytest.mark.asyncio
async def test_scheduler_cancels_due_open_and_filling_queues(session: AsyncSession) -> None:
    open_context = await _build_context(session, guild_discord_id=9401)
    filling_context = await _build_context(session, guild_discord_id=9402)
    open_queue = await _create_open_queue(open_context, created_at_offset_seconds=-400, queue_timeout_seconds=300)
    filling_queue = await _create_filling_queue(filling_context, created_at_offset_seconds=-301, queue_timeout_seconds=300)
    refreshed: list[tuple[int, QueueState, str | None]] = []

    class FakeGuild:
        def get_channel(self, _channel_id: int):
            return None

    async def refresh_queue_public_message(_guild, snapshot) -> None:
        refreshed.append((snapshot.queue.guild_id, snapshot.queue.state, snapshot.queue.cancel_reason))

    bot = SimpleNamespace(
        runtime=build_fake_runtime(session, open_context.services),
        logger=NullLogger(),
        get_guild=lambda _guild_id: FakeGuild(),
        refresh_queue_public_message=refresh_queue_public_message,
        build_notice_embed=lambda *_args, **_kwargs: None,
    )
    await SchedulerWorker().process_deadlines(bot)

    open_snapshot = await open_context.repos.matches.get_queue_snapshot(open_queue.queue_id)
    filling_snapshot = await filling_context.repos.matches.get_queue_snapshot(filling_queue.queue_id)

    assert open_snapshot is not None
    assert open_snapshot.queue.state == QueueState.QUEUE_CANCELLED
    assert open_snapshot.queue.cancel_reason == "queue_timeout"
    assert filling_snapshot is not None
    assert filling_snapshot.queue.state == QueueState.QUEUE_CANCELLED
    assert filling_snapshot.queue.cancel_reason == "queue_timeout"
    assert refreshed == [
        (open_context.guild.id, QueueState.QUEUE_CANCELLED, "queue_timeout"),
        (filling_context.guild.id, QueueState.QUEUE_CANCELLED, "queue_timeout"),
    ]


@pytest.mark.asyncio
async def test_scheduler_leaves_non_due_open_and_filling_queues_alone(session: AsyncSession) -> None:
    open_context = await _build_context(session, guild_discord_id=9403)
    filling_context = await _build_context(session, guild_discord_id=9404)
    open_queue = await _create_open_queue(open_context, created_at_offset_seconds=-120, queue_timeout_seconds=300)
    filling_queue = await _create_filling_queue(filling_context, created_at_offset_seconds=-299, queue_timeout_seconds=300)

    bot = SimpleNamespace(
        runtime=build_fake_runtime(session, open_context.services),
        logger=NullLogger(),
        get_guild=lambda _guild_id: None,
        refresh_queue_public_message=lambda *_args, **_kwargs: None,
        build_notice_embed=lambda *_args, **_kwargs: None,
    )
    worker = SchedulerWorker()
    await worker.process_deadlines(bot)

    open_snapshot = await open_context.repos.matches.get_queue_snapshot(open_queue.queue_id)
    filling_snapshot = await filling_context.repos.matches.get_queue_snapshot(filling_queue.queue_id)

    assert open_snapshot is not None
    assert open_snapshot.queue.state == QueueState.QUEUE_OPEN
    assert filling_snapshot is not None
    assert filling_snapshot.queue.state == QueueState.FILLING
    assert worker.last_summary["queue_timeouts"] == 0


@pytest.mark.asyncio
async def test_scheduler_respects_per_guild_queue_timeout_seconds(session: AsyncSession) -> None:
    short_context = await _build_context(session, guild_discord_id=9405)
    long_context = await _build_context(session, guild_discord_id=9406)
    short_queue = await _create_open_queue(short_context, created_at_offset_seconds=-200, queue_timeout_seconds=180)
    long_queue = await _create_open_queue(long_context, created_at_offset_seconds=-200, queue_timeout_seconds=600)

    bot = SimpleNamespace(
        runtime=build_fake_runtime(session, short_context.services),
        logger=NullLogger(),
        get_guild=lambda _guild_id: None,
        refresh_queue_public_message=lambda *_args, **_kwargs: None,
        build_notice_embed=lambda *_args, **_kwargs: None,
    )
    worker = SchedulerWorker()
    await worker.process_deadlines(bot)

    short_snapshot = await short_context.repos.matches.get_queue_snapshot(short_queue.queue_id)
    long_snapshot = await long_context.repos.matches.get_queue_snapshot(long_queue.queue_id)

    assert short_snapshot is not None
    assert short_snapshot.queue.state == QueueState.QUEUE_CANCELLED
    assert short_snapshot.queue.cancel_reason == "queue_timeout"
    assert long_snapshot is not None
    assert long_snapshot.queue.state == QueueState.QUEUE_OPEN
    assert worker.last_summary["queue_timeouts"] == 1


@pytest.mark.asyncio
async def test_scheduler_keeps_ready_check_timeout_path_unchanged(session: AsyncSession) -> None:
    context = await _build_context(session, guild_discord_id=9407)
    queue_context = await _create_ready_check_queue(context)
    refreshed: list[tuple[QueueState, str | None]] = []

    class FakeGuild:
        def get_channel(self, _channel_id: int):
            return None

    async def refresh_queue_public_message(_guild, snapshot) -> None:
        refreshed.append((snapshot.queue.state, snapshot.queue.cancel_reason))

    bot = SimpleNamespace(
        runtime=build_fake_runtime(session, context.services),
        logger=NullLogger(),
        get_guild=lambda _guild_id: FakeGuild(),
        refresh_queue_public_message=refresh_queue_public_message,
        build_notice_embed=lambda *_args, **_kwargs: None,
    )
    worker = SchedulerWorker()
    await worker.process_deadlines(bot)

    snapshot = await context.repos.matches.get_queue_snapshot(queue_context.queue_id)

    assert snapshot is not None
    assert snapshot.queue.state == QueueState.READY_CHECK
    assert worker.last_summary["queue_timeouts"] == 0
    assert worker.last_summary["ready_check_timeouts"] == 0
    assert refreshed == []
