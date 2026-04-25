from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import ActivityKind, MatchMode, QueueState, RulesetKey
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
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService
from highlight_manager.tasks.cleanup import CleanupWorker
from highlight_manager.tasks.recovery import RecoveryCoordinator


class NullLogger:
    def info(self, *_args, **_kwargs) -> None:
        return None

    def warning(self, *_args, **_kwargs) -> None:
        return None


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'ready-check-recovery.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class ReadyCheckContext:
    queue_id: UUID
    creator_id: int
    opponent_id: int
    public_message_id: int


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
        economy=EconomyRepository(session),
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


async def create_ready_check_queue(
    session: AsyncSession,
    services: SimpleNamespace,
    *,
    guild_discord_id: int,
    public_message_id: int,
) -> ReadyCheckContext:
    repos = build_repositories(session)
    bundle = await services.guilds.ensure_guild(repos.guilds, guild_discord_id, "Highlight")
    season = await services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
    creator = await services.profiles.ensure_player(
        repos.profiles,
        bundle.guild.id,
        guild_discord_id * 10 + 1,
        display_name="Creator",
    )
    opponent = await services.profiles.ensure_player(
        repos.profiles,
        bundle.guild.id,
        guild_discord_id * 10 + 2,
        display_name="Opponent",
    )
    queue = await services.matches.create_queue(
        repos.matches,
        repos.profiles,
        repos.moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=creator.id,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=555,
    )
    ready_check = await services.matches.join_queue(
        repos.matches,
        repos.profiles,
        repos.moderation,
        queue_id=queue.queue.id,
        player_id=opponent.id,
        team_number=2,
    )
    assert ready_check.queue.state == QueueState.READY_CHECK
    await repos.matches.set_queue_public_message_id(ready_check.queue.id, public_message_id)
    return ReadyCheckContext(
        queue_id=ready_check.queue.id,
        creator_id=creator.id,
        opponent_id=opponent.id,
        public_message_id=public_message_id,
    )


@pytest.mark.asyncio
async def test_active_queue_query_includes_ready_check(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    services = build_services(settings)
    context = await create_ready_check_queue(
        session,
        services,
        guild_discord_id=9101,
        public_message_id=910101,
    )

    active_queues = await MatchRepository(session).list_active_queues()

    assert context.queue_id in {queue.id for queue in active_queues}


@pytest.mark.asyncio
async def test_recovery_restores_ready_check_queue_view(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    services = build_services(settings)
    context = await create_ready_check_queue(
        session,
        services,
        guild_discord_id=9102,
        public_message_id=910201,
    )
    repos = build_repositories(session)
    await services.matches.mark_ready(
        repos.matches,
        repos.profiles,
        queue_id=context.queue_id,
        player_id=context.creator_id,
    )
    restored_views: list[tuple[int, UUID, QueueState, set[int]]] = []

    class FakeBot:
        def __init__(self) -> None:
            self.runtime = build_fake_runtime(session, services)

        def add_view(self, view, *, message_id: int) -> None:
            restored_views.append((message_id, view.queue_id, view.state, view.ready_player_ids))

        def build_queue_view(self, queue_id, *, snapshot=None):
            assert snapshot is not None
            return SimpleNamespace(
                queue_id=queue_id,
                state=snapshot.queue.state,
                ready_player_ids=set(snapshot.ready_player_ids),
            )

        def build_match_view(self, match_id, *, snapshot=None):
            raise AssertionError("No match views should be restored in this test.")

    restored = await RecoveryCoordinator().restore_views(FakeBot())

    assert restored == 1
    assert restored_views == [
        (context.public_message_id, context.queue_id, QueueState.READY_CHECK, {context.creator_id})
    ]


@pytest.mark.asyncio
async def test_cleanup_does_not_clear_ready_check_queue_activity(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    services = build_services(settings)
    context = await create_ready_check_queue(
        session,
        services,
        guild_discord_id=9103,
        public_message_id=910301,
    )
    runtime = build_fake_runtime(session, services)
    bot = SimpleNamespace(
        runtime=runtime,
        logger=NullLogger(),
        get_guild=lambda _guild_id: None,
    )

    worker = CleanupWorker()
    await worker.run(bot)
    repos = build_repositories(session)
    creator_activity = await repos.profiles.ensure_activity(context.creator_id)
    opponent_activity = await repos.profiles.ensure_activity(context.opponent_id)

    assert worker.last_summary["cleared_orphaned_activities"] == 0
    assert creator_activity.activity_kind == ActivityKind.QUEUE
    assert creator_activity.queue_id == context.queue_id
    assert opponent_activity.activity_kind == ActivityKind.QUEUE
    assert opponent_activity.queue_id == context.queue_id
