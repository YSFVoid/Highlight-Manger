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
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'ready-check-scheduler.db'}")
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
    player_ids: list[int]


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


async def _create_ready_check_queue(
    context: SimpleNamespace,
    *,
    deadline_offset_seconds: int,
    ruleset_key: RulesetKey = RulesetKey.APOSTADO,
) -> QueueContext:
    players = await _create_players(context, 2)
    queue = await context.services.matches.create_queue(
        context.repos.matches,
        context.repos.profiles,
        context.repos.moderation,
        guild_id=context.guild.id,
        season_id=context.season.id,
        creator_player_id=players[0].id,
        ruleset_key=ruleset_key,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=555,
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
    await context.repos.matches.set_queue_public_message_id(snapshot.queue.id, 880001 + len(players))
    queue_row = await context.repos.matches.get_queue(snapshot.queue.id, for_update=True)
    assert queue_row is not None
    queue_row.room_info_deadline_at = utcnow() + timedelta(seconds=deadline_offset_seconds)
    await context.repos.matches.session.flush()
    return QueueContext(queue_id=snapshot.queue.id, player_ids=[player.id for player in players])


async def _create_pending_room_info_queue(
    context: SimpleNamespace,
    *,
    deadline_offset_seconds: int,
) -> QueueContext:
    ready_context = await _create_ready_check_queue(context, deadline_offset_seconds=120)
    for player_id in ready_context.player_ids:
        snapshot = await context.services.matches.mark_ready(
            context.repos.matches,
            context.repos.profiles,
            queue_id=ready_context.queue_id,
            player_id=player_id,
        )
    assert snapshot.queue.state == QueueState.FULL_PENDING_ROOM_INFO
    queue_row = await context.repos.matches.get_queue(ready_context.queue_id, for_update=True)
    assert queue_row is not None
    queue_row.room_info_deadline_at = utcnow() + timedelta(seconds=deadline_offset_seconds)
    await context.repos.matches.session.flush()
    return ready_context


@pytest.mark.asyncio
async def test_scheduler_cancels_due_ready_check_queues_only(session: AsyncSession) -> None:
    context = await _build_context(session, guild_discord_id=9301)
    due_queue = await _create_ready_check_queue(context, deadline_offset_seconds=-5)
    not_due_queue = await _create_ready_check_queue(
        context,
        deadline_offset_seconds=120,
        ruleset_key=RulesetKey.HIGHLIGHT,
    )
    refreshed: list[tuple[int, QueueState, str | None]] = []

    class FakeGuild:
        def get_channel(self, _channel_id: int):
            return None

    async def refresh_queue_public_message(_guild, snapshot) -> None:
        refreshed.append((snapshot.queue.guild_id, snapshot.queue.state, snapshot.queue.cancel_reason))

    bot = SimpleNamespace(
        runtime=build_fake_runtime(session, context.services),
        logger=NullLogger(),
        get_guild=lambda _guild_id: FakeGuild(),
        refresh_queue_public_message=refresh_queue_public_message,
    )
    worker = SchedulerWorker()
    await worker.process_deadlines(bot)

    due_snapshot = await context.repos.matches.get_queue_snapshot(due_queue.queue_id)
    not_due_snapshot = await context.repos.matches.get_queue_snapshot(not_due_queue.queue_id)

    assert due_snapshot is not None
    assert due_snapshot.queue.state == QueueState.QUEUE_CANCELLED
    assert due_snapshot.queue.cancel_reason == "ready_check_timeout"
    assert not_due_snapshot is not None
    assert not_due_snapshot.queue.state == QueueState.READY_CHECK
    assert worker.last_summary["ready_check_timeouts"] == 1
    assert refreshed == [(context.guild.id, QueueState.QUEUE_CANCELLED, "ready_check_timeout")]


@pytest.mark.asyncio
async def test_scheduler_keeps_room_info_timeout_behavior_unchanged(session: AsyncSession) -> None:
    context = await _build_context(session, guild_discord_id=9302)
    queue_context = await _create_pending_room_info_queue(context, deadline_offset_seconds=-5)
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
    assert snapshot.queue.state == QueueState.QUEUE_CANCELLED
    assert snapshot.queue.cancel_reason == "room_info_timeout"
    assert worker.last_summary["room_info_timeouts"] == 1
    assert refreshed == [(QueueState.QUEUE_CANCELLED, "room_info_timeout")]
