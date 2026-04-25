from __future__ import annotations

import inspect
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.bot import HighlightBot, PlayerCommands
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.models.core import PlayerActivityStateModel
from highlight_manager.db.models.competitive import QueueModel
from highlight_manager.db.models.moderation import AuditLogModel
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import AuditAction, MatchMode, QueueState, RulesetKey
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.matches.types import QueueSnapshot
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'duplicate-queue-prevention.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class DuplicateQueueContext:
    match_service: MatchService
    matches: MatchRepository
    profiles: ProfileRepository
    moderation: ModerationRepository
    guild_id: int
    season_id: int
    next_discord_id: int


async def _build_context(session: AsyncSession, *, discord_guild_id: int = 9501) -> DuplicateQueueContext:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
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
    bundle = await GuildService(settings).ensure_guild(guilds, discord_guild_id, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    return DuplicateQueueContext(
        match_service=match_service,
        matches=matches,
        profiles=profiles,
        moderation=moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        next_discord_id=discord_guild_id * 10,
    )


async def _create_player(context: DuplicateQueueContext):
    player = await ProfileService().ensure_player(
        context.profiles,
        context.guild_id,
        context.next_discord_id,
        display_name=f"Player {context.next_discord_id}",
    )
    context.next_discord_id += 1
    return player


async def _create_queue(
    context: DuplicateQueueContext,
    *,
    player=None,
    ruleset_key=RulesetKey.APOSTADO,
    mode=MatchMode.TWO_V_TWO,
    source_channel_id: int | None = 777,
):
    player = player or await _create_player(context)
    return await context.match_service.create_queue(
        context.matches,
        context.profiles,
        context.moderation,
        guild_id=context.guild_id,
        season_id=context.season_id,
        creator_player_id=player.id,
        ruleset_key=ruleset_key,
        mode=mode,
        source_channel_id=source_channel_id,
    )


async def _queue_created_audit_count(session: AsyncSession) -> int:
    value = await session.scalar(
        select(func.count())
        .select_from(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.QUEUE_CREATED)
    )
    return int(value or 0)


async def _queue_count(session: AsyncSession) -> int:
    value = await session.scalar(select(func.count()).select_from(QueueModel))
    return int(value or 0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        QueueState.QUEUE_OPEN,
        QueueState.FILLING,
        QueueState.READY_CHECK,
        QueueState.FULL_PENDING_ROOM_INFO,
    ],
)
async def test_active_queue_for_same_playlist_is_reused(session: AsyncSession, state: QueueState) -> None:
    context = await _build_context(session, discord_guild_id=9501 + len(state.value))
    existing_creator = await _create_player(context)
    requester = await _create_player(context)
    existing = await _create_queue(context, player=existing_creator)
    existing.queue.state = state
    await context.matches.session.flush()

    reused = await _create_queue(context, player=requester)
    activity = await session.get(PlayerActivityStateModel, requester.id)

    assert reused.queue.id == existing.queue.id
    assert reused.reused_existing is True
    assert await _queue_count(session) == 1
    assert activity is None
    assert await _queue_created_audit_count(session) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal_state", [QueueState.QUEUE_CANCELLED, QueueState.CONVERTED_TO_MATCH])
async def test_terminal_queues_do_not_block_new_creation(session: AsyncSession, terminal_state: QueueState) -> None:
    context = await _build_context(session, discord_guild_id=9510 + len(terminal_state.value))
    existing = await _create_queue(context)
    existing.queue.state = terminal_state
    await context.matches.session.flush()

    created = await _create_queue(context)

    assert created.queue.id != existing.queue.id
    assert created.reused_existing is False
    assert await _queue_created_audit_count(session) == 2


@pytest.mark.asyncio
async def test_different_guild_ruleset_or_mode_does_not_reuse_queue(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9521)
    other_guild_context = await _build_context(session, discord_guild_id=9522)
    existing = await _create_queue(context)

    different_ruleset = await _create_queue(context, ruleset_key=RulesetKey.HIGHLIGHT)
    different_mode = await _create_queue(context, mode=MatchMode.ONE_V_ONE)
    different_guild = await _create_queue(other_guild_context)

    assert different_ruleset.queue.id != existing.queue.id
    assert different_mode.queue.id != existing.queue.id
    assert different_guild.queue.id != existing.queue.id
    assert different_ruleset.reused_existing is False
    assert different_mode.reused_existing is False
    assert different_guild.reused_existing is False


def test_existing_queue_notice_includes_jump_link() -> None:
    queue_id = uuid4()
    queue = type(
        "Queue",
        (),
        {
            "id": queue_id,
            "guild_id": 1,
            "season_id": 1,
            "creator_player_id": 1,
            "ruleset_key": RulesetKey.APOSTADO,
            "mode": MatchMode.TWO_V_TWO,
            "state": QueueState.FILLING,
            "team_size": 2,
            "source_channel_id": 1234,
            "public_message_id": 5678,
        },
    )()
    players = [
        type("QueuePlayer", (), {"player_id": 1, "team_number": 1, "ready_at": None})(),
        type("QueuePlayer", (), {"player_id": 2, "team_number": 2, "ready_at": None})(),
    ]
    snapshot = QueueSnapshot(queue=queue, players=players, player_discord_ids={})
    guild = type("Guild", (), {"id": 9999})()

    embed = HighlightBot.build_existing_queue_notice_embed(guild, snapshot)

    assert embed.title == "Queue already exists"
    assert "Apostado 2V2" in embed.description
    assert "https://discord.com/channels/9999/1234/5678" in embed.description


def test_existing_queue_notice_fallback_when_message_missing() -> None:
    queue = type(
        "Queue",
        (),
        {
            "guild_id": 1,
            "season_id": 1,
            "creator_player_id": 1,
            "ruleset_key": RulesetKey.HIGHLIGHT,
            "mode": MatchMode.ONE_V_ONE,
            "state": QueueState.QUEUE_OPEN,
            "team_size": 1,
            "source_channel_id": None,
            "public_message_id": None,
        },
    )()
    snapshot = QueueSnapshot(queue=queue, players=[], player_discord_ids={})
    guild = type("Guild", (), {"id": 9999})()

    embed = HighlightBot.build_existing_queue_notice_embed(guild, snapshot)

    assert "public card could not be linked" in embed.description


def test_play_surfaces_use_existing_queue_notice() -> None:
    play_source = inspect.getsource(PlayerCommands.play.callback)
    picker_source = inspect.getsource(HighlightBot.build_play_picker_view)

    assert "snapshot.reused_existing" in play_source
    assert "build_existing_queue_notice_embed" in play_source
    assert "snapshot.reused_existing" in picker_source
    assert "build_existing_queue_notice_embed" in picker_source
    assert "ephemeral=True" in picker_source
