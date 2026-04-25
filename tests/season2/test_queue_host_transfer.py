from __future__ import annotations

import inspect
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.bot import HighlightBot, QueueActionView
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.models.competitive import QueueModel, QueuePlayerModel
from highlight_manager.db.models.moderation import AuditLogModel
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import AuditAction, MatchMode, QueueState, RulesetKey
from highlight_manager.modules.common.exceptions import StateTransitionError, ValidationError
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.matches.types import QueueSnapshot
from highlight_manager.modules.matches.ui import build_queue_embed
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'queue-host-transfer.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class HostTransferContext:
    session: AsyncSession
    guild_id: int
    season_id: int
    profiles: ProfileRepository
    matches: MatchRepository
    moderation: ModerationRepository
    profile_service: ProfileService
    match_service: MatchService
    next_discord_user_id: int = 20_000


async def _build_context(session: AsyncSession, *, discord_guild_id: int = 9201) -> HostTransferContext:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    profile_service = ProfileService()
    season_service = SeasonService()
    moderation_service = ModerationService()
    match_service = MatchService(
        settings,
        profile_service=profile_service,
        season_service=season_service,
        rank_service=RankService(),
        economy_service=EconomyService(),
        moderation_service=moderation_service,
    )
    guilds = GuildRepository(session)
    profiles = ProfileRepository(session)
    seasons = SeasonRepository(session)
    matches = MatchRepository(session)
    moderation = ModerationRepository(session)
    bundle = await guild_service.ensure_guild(guilds, discord_guild_id, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    return HostTransferContext(
        session=session,
        guild_id=bundle.guild.id,
        season_id=season.id,
        profiles=profiles,
        matches=matches,
        moderation=moderation,
        profile_service=profile_service,
        match_service=match_service,
    )


async def _create_players(context: HostTransferContext, count: int):
    players = []
    for index in range(count):
        discord_user_id = context.next_discord_user_id + index
        players.append(
            await context.profile_service.ensure_player(
                context.profiles,
                context.guild_id,
                discord_user_id,
                display_name=f"Player {discord_user_id}",
            )
        )
    context.next_discord_user_id += count
    return players


async def _create_filled_queue(
    context: HostTransferContext,
    *,
    mode: MatchMode = MatchMode.TWO_V_TWO,
) -> tuple[QueueSnapshot, list]:
    players = await _create_players(context, mode.team_size * 2)
    queue = await context.match_service.create_queue(
        context.matches,
        context.profiles,
        context.moderation,
        guild_id=context.guild_id,
        season_id=context.season_id,
        creator_player_id=players[0].id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=mode,
        source_channel_id=777,
    )
    for player in players[1:mode.team_size]:
        await context.match_service.join_queue(
            context.matches,
            context.profiles,
            context.moderation,
            queue_id=queue.queue.id,
            player_id=player.id,
            team_number=1,
        )
    snapshot = queue
    for player in players[mode.team_size:]:
        snapshot = await context.match_service.join_queue(
            context.matches,
            context.profiles,
            context.moderation,
            queue_id=queue.queue.id,
            player_id=player.id,
            team_number=2,
        )
    assert snapshot.queue.state == QueueState.READY_CHECK
    return snapshot, players


async def _mark_ready(context: HostTransferContext, snapshot: QueueSnapshot, player_ids: list[int]) -> QueueSnapshot:
    ready_snapshot = snapshot
    for player_id in player_ids:
        ready_snapshot = await context.match_service.mark_ready(
            context.matches,
            context.profiles,
            queue_id=snapshot.queue.id,
            player_id=player_id,
        )
    return ready_snapshot


@pytest.mark.asyncio
async def test_current_host_transfers_to_participant_and_preserves_ready_state(session: AsyncSession) -> None:
    context = await _build_context(session)
    snapshot, players = await _create_filled_queue(context)
    snapshot = await _mark_ready(context, snapshot, [players[0].id, players[1].id])

    transferred = await context.match_service.transfer_queue_host(
        context.matches,
        context.moderation,
        queue_id=snapshot.queue.id,
        actor_player_id=players[0].id,
        target_player_id=players[1].id,
        actor_is_staff=False,
    )

    assert transferred.queue.creator_player_id == players[1].id
    assert transferred.queue.state == QueueState.READY_CHECK
    assert transferred.ready_player_ids == {players[0].id, players[1].id}
    refetched = await context.matches.get_queue_snapshot(snapshot.queue.id)
    assert refetched is not None
    assert refetched.queue.creator_player_id == players[1].id
    assert refetched.ready_player_ids == {players[0].id, players[1].id}

    audit = await context.session.scalar(
        select(AuditLogModel)
        .where(AuditLogModel.action == AuditAction.QUEUE_HOST_TRANSFERRED)
        .order_by(AuditLogModel.id.desc())
    )
    assert audit is not None
    assert audit.actor_player_id == players[0].id
    assert audit.target_player_id == players[1].id
    assert audit.metadata_json == {
        "old_creator_player_id": players[0].id,
        "new_creator_player_id": players[1].id,
        "queue_state": QueueState.READY_CHECK.value,
    }


@pytest.mark.asyncio
async def test_staff_can_transfer_but_non_host_non_staff_cannot(session: AsyncSession) -> None:
    context = await _build_context(session)
    snapshot, players = await _create_filled_queue(context)
    staff = (await _create_players(context, 1))[0]

    transferred = await context.match_service.transfer_queue_host(
        context.matches,
        context.moderation,
        queue_id=snapshot.queue.id,
        actor_player_id=staff.id,
        target_player_id=players[1].id,
        actor_is_staff=True,
    )
    assert transferred.queue.creator_player_id == players[1].id

    with pytest.raises(ValidationError, match="Only the current host or staff"):
        await context.match_service.transfer_queue_host(
            context.matches,
            context.moderation,
            queue_id=snapshot.queue.id,
            actor_player_id=players[2].id,
            target_player_id=players[3].id,
            actor_is_staff=False,
        )


@pytest.mark.asyncio
async def test_transfer_rejects_non_participant_current_host_and_terminal_queues(session: AsyncSession) -> None:
    context = await _build_context(session)
    snapshot, players = await _create_filled_queue(context)
    outsider = (await _create_players(context, 1))[0]

    with pytest.raises(ValidationError, match="already the queue host"):
        await context.match_service.transfer_queue_host(
            context.matches,
            context.moderation,
            queue_id=snapshot.queue.id,
            actor_player_id=players[0].id,
            target_player_id=players[0].id,
            actor_is_staff=False,
        )
    with pytest.raises(ValidationError, match="already be in this queue"):
        await context.match_service.transfer_queue_host(
            context.matches,
            context.moderation,
            queue_id=snapshot.queue.id,
            actor_player_id=players[0].id,
            target_player_id=outsider.id,
            actor_is_staff=False,
        )

    await context.match_service.cancel_queue(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=snapshot.queue.id,
        actor_player_id=players[0].id,
        reason="test_cancel",
    )
    with pytest.raises(StateTransitionError):
        await context.match_service.transfer_queue_host(
            context.matches,
            context.moderation,
            queue_id=snapshot.queue.id,
            actor_player_id=players[0].id,
            target_player_id=players[1].id,
            actor_is_staff=False,
        )


@pytest.mark.asyncio
async def test_transferred_host_controls_room_info_and_match_creator(session: AsyncSession) -> None:
    context = await _build_context(session)
    snapshot, players = await _create_filled_queue(context, mode=MatchMode.ONE_V_ONE)
    snapshot = await _mark_ready(context, snapshot, [players[0].id, players[1].id])
    assert snapshot.queue.state == QueueState.FULL_PENDING_ROOM_INFO

    await context.match_service.transfer_queue_host(
        context.matches,
        context.moderation,
        queue_id=snapshot.queue.id,
        actor_player_id=players[0].id,
        target_player_id=players[1].id,
        actor_is_staff=False,
    )

    with pytest.raises(ValidationError, match="Only the creator or staff"):
        await context.match_service.submit_room_info(
            context.matches,
            context.profiles,
            context.moderation,
            queue_id=snapshot.queue.id,
            submitter_player_id=players[0].id,
            is_moderator=False,
            room_code="ROOM-1",
            room_password="PW-1",
            room_notes=None,
        )

    match = await context.match_service.submit_room_info(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=snapshot.queue.id,
        submitter_player_id=players[1].id,
        is_moderator=False,
        room_code="ROOM-1",
        room_password="PW-1",
        room_notes=None,
    )

    assert match.match.creator_player_id == players[1].id
    assert match.match.team1_captain_player_id == players[0].id
    assert match.match.team2_captain_player_id == players[1].id
    assert match.match.room_info_submitted_by_player_id == players[1].id


def test_queue_action_view_exposes_transfer_host_for_mutable_queues() -> None:
    snapshot = SimpleNamespace(
        queue=SimpleNamespace(state=QueueState.FILLING, team_size=2),
        team1_ids=[1],
        team2_ids=[],
    )

    view = QueueActionView(SimpleNamespace(), uuid4(), snapshot=snapshot)

    assert view.transfer_host.disabled is False
    assert view.transfer_host.custom_id.endswith(":transfer-host")


def test_queue_action_view_disables_transfer_host_for_closed_queues() -> None:
    snapshot = SimpleNamespace(
        queue=SimpleNamespace(state=QueueState.CONVERTED_TO_MATCH, team_size=1),
        team1_ids=[1],
        team2_ids=[2],
    )

    view = QueueActionView(SimpleNamespace(), uuid4(), snapshot=snapshot)

    assert view.transfer_host.disabled is True


def test_queue_embed_renders_refetched_transferred_host() -> None:
    queue_id = uuid4()
    queue = QueueModel(
        id=queue_id,
        guild_id=1,
        season_id=1,
        creator_player_id=2,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.TWO_V_TWO,
        state=QueueState.FILLING,
        team_size=2,
    )
    snapshot = QueueSnapshot(
        queue=queue,
        players=[
            QueuePlayerModel(queue_id=queue_id, player_id=1, team_number=1),
            QueuePlayerModel(queue_id=queue_id, player_id=2, team_number=1),
        ],
        player_discord_ids={1: 101, 2: 102},
    )

    embed = build_queue_embed(snapshot)

    assert "<@102>" in embed.description


def test_queue_host_transfer_surface_is_wired() -> None:
    source = inspect.getsource(HighlightBot)

    assert "handle_queue_host_transfer" in source
    assert "transfer_queue_host" in source
    assert "refresh_queue_public_message" in source
