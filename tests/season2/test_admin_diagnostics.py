from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.bot import HighlightBot
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.models.competitive import MatchModel, MatchPlayerModel, QueueModel
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import (
    ActivityKind,
    MatchMode,
    MatchResultPhase,
    MatchState,
    QueueState,
    RulesetKey,
)
from highlight_manager.modules.diagnostics.service import AdminDiagnosticsService
from highlight_manager.modules.diagnostics.ui import build_admin_diagnostics_embed
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'admin-diagnostics.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class DiagnosticsContext:
    session: AsyncSession
    guild_id: int
    season_id: int
    profiles: ProfileRepository
    matches: MatchRepository
    match_service: MatchService
    next_discord_user_id: int = 50_000
    next_match_number: int = 1


async def _build_context(session: AsyncSession, *, discord_guild_id: int) -> DiagnosticsContext:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
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
    bundle = await guild_service.ensure_guild(guilds, discord_guild_id, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    return DiagnosticsContext(
        session=session,
        guild_id=bundle.guild.id,
        season_id=season.id,
        profiles=profiles,
        matches=MatchRepository(session),
        match_service=match_service,
    )


async def _create_players(context: DiagnosticsContext, count: int):
    service = ProfileService()
    players = []
    for _ in range(count):
        discord_user_id = context.next_discord_user_id
        context.next_discord_user_id += 1
        players.append(
            await service.ensure_player(
                context.profiles,
                context.guild_id,
                discord_user_id,
                display_name=f"Player {discord_user_id}",
            )
        )
    return players


async def _create_queue(
    context: DiagnosticsContext,
    *,
    state: QueueState,
    creator_player_id: int | None = None,
) -> QueueModel:
    if creator_player_id is None:
        creator_player_id = (await _create_players(context, 1))[0].id
    queue = QueueModel(
        guild_id=context.guild_id,
        season_id=context.season_id,
        creator_player_id=creator_player_id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.TWO_V_TWO,
        state=state,
        team_size=2,
        source_channel_id=777,
    )
    context.session.add(queue)
    await context.session.flush()
    return queue


async def _create_match(
    context: DiagnosticsContext,
    *,
    state: MatchState,
    phase: MatchResultPhase,
    now: datetime,
    captain_deadline_at: datetime | None = None,
    fallback_deadline_at: datetime | None = None,
    result_deadline_at: datetime | None = None,
) -> tuple[MatchModel, list[int]]:
    players = await _create_players(context, 4)
    queue = await _create_queue(
        context,
        state=QueueState.CONVERTED_TO_MATCH,
        creator_player_id=players[0].id,
    )
    terminal_states = {
        MatchState.EXPIRED,
        MatchState.CONFIRMED,
        MatchState.CANCELLED,
        MatchState.FORCE_CLOSED,
    }
    match = MatchModel(
        guild_id=context.guild_id,
        season_id=context.season_id,
        queue_id=queue.id,
        match_number=context.next_match_number,
        creator_player_id=players[0].id,
        team1_captain_player_id=players[0].id,
        team2_captain_player_id=players[2].id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.TWO_V_TWO,
        state=state,
        result_phase=phase,
        team_size=2,
        result_channel_id=1000 + context.next_match_number,
        team1_voice_channel_id=2000 + context.next_match_number,
        team2_voice_channel_id=3000 + context.next_match_number,
        captain_deadline_at=captain_deadline_at,
        fallback_deadline_at=fallback_deadline_at,
        result_deadline_at=result_deadline_at,
        closed_at=now - timedelta(minutes=1) if state in terminal_states else None,
    )
    context.next_match_number += 1
    context.session.add(match)
    await context.session.flush()
    for player, team_number in zip(players, [1, 1, 2, 2], strict=True):
        context.session.add(
            MatchPlayerModel(
                match_id=match.id,
                player_id=player.id,
                team_number=team_number,
            )
        )
    await context.session.flush()
    return match, [player.id for player in players]


@pytest.mark.asyncio
async def test_admin_diagnostics_collects_aggregate_runtime_counts(session: AsyncSession) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    context = await _build_context(session, discord_guild_id=9100)

    await _create_queue(context, state=QueueState.READY_CHECK)
    expired, _ = await _create_match(
        context,
        state=MatchState.EXPIRED,
        phase=MatchResultPhase.STAFF_REVIEW,
        now=now,
        result_deadline_at=now - timedelta(minutes=30),
    )
    overdue, _ = await _create_match(
        context,
        state=MatchState.LIVE,
        phase=MatchResultPhase.CAPTAIN,
        now=now,
        captain_deadline_at=now - timedelta(minutes=5),
        result_deadline_at=now + timedelta(minutes=30),
    )
    disputed, disputed_player_ids = await _create_match(
        context,
        state=MatchState.RESULT_PENDING,
        phase=MatchResultPhase.FALLBACK,
        now=now,
        fallback_deadline_at=now + timedelta(minutes=30),
        result_deadline_at=now + timedelta(minutes=30),
    )
    await context.matches.create_vote(
        match_id=disputed.id,
        player_id=disputed_player_ids[0],
        winner_team_number=1,
        winner_mvp_player_id=None,
        loser_mvp_player_id=None,
    )
    await context.matches.create_vote(
        match_id=disputed.id,
        player_id=disputed_player_ids[1],
        winner_team_number=2,
        winner_mvp_player_id=None,
        loser_mvp_player_id=None,
    )
    confirmed, _ = await _create_match(
        context,
        state=MatchState.CONFIRMED,
        phase=MatchResultPhase.STAFF_REVIEW,
        now=now,
        result_deadline_at=now - timedelta(minutes=30),
    )
    stale_player = (await _create_players(context, 1))[0]
    stale_queue = await _create_queue(context, state=QueueState.QUEUE_CANCELLED)
    await context.profiles.set_activity(
        stale_player.id,
        activity_kind=ActivityKind.QUEUE,
        queue_id=stale_queue.id,
    )
    other_context = await _build_context(session, discord_guild_id=9101)
    other_player = (await _create_players(other_context, 1))[0]
    other_queue = await _create_queue(other_context, state=QueueState.QUEUE_CANCELLED)
    await other_context.profiles.set_activity(
        other_player.id,
        activity_kind=ActivityKind.QUEUE,
        queue_id=other_queue.id,
    )

    snapshot = await AdminDiagnosticsService().collect(
        session=session,
        matches=context.matches,
        profiles=context.profiles,
        match_service=context.match_service,
        guild_id=context.guild_id,
        now=now,
        channel_exists=lambda _channel_id: True,
        voice_status=None,
        voice_enabled=False,
        voice_channel_id=None,
        startup_health={"db_ready": True, "views_restored": 3, "assets_warmed": True},
        command_sync_status={"scope": "guild", "success": True, "count": 4},
    )

    assert snapshot.unresolved_matches.staff_review == 1
    assert snapshot.unresolved_matches.overdue == 1
    assert snapshot.unresolved_matches.disputed == 1
    assert snapshot.unresolved_matches.total == 3
    assert snapshot.queue_counts[QueueState.READY_CHECK] == 1
    assert snapshot.match_counts[MatchState.EXPIRED] == 1
    assert snapshot.match_counts[MatchState.LIVE] == 1
    assert snapshot.match_counts[MatchState.RESULT_PENDING] == 1
    assert MatchState.CONFIRMED not in snapshot.match_counts
    assert snapshot.backlog.captain_fallback_opens == 1
    assert snapshot.backlog.stale_activity_rows == 1
    assert snapshot.schema is not None
    assert snapshot.schema.status in {"ok", "unknown"}
    assert confirmed.id != expired.id
    assert overdue.id != disputed.id


@pytest.mark.asyncio
async def test_admin_diagnostics_embed_is_summary_only(session: AsyncSession) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    context = await _build_context(session, discord_guild_id=9102)
    await _create_queue(context, state=QueueState.READY_CHECK)
    await _create_match(
        context,
        state=MatchState.EXPIRED,
        phase=MatchResultPhase.STAFF_REVIEW,
        now=now,
        result_deadline_at=now - timedelta(minutes=30),
    )
    snapshot = await AdminDiagnosticsService().collect(
        session=session,
        matches=context.matches,
        profiles=context.profiles,
        match_service=context.match_service,
        guild_id=context.guild_id,
        now=now,
        channel_exists=lambda _channel_id: True,
        voice_status=None,
        voice_enabled=True,
        voice_channel_id=12345,
    )

    embed = build_admin_diagnostics_embed(snapshot)
    field_names = {field.name for field in embed.fields}
    rendered_text = "\n".join(
        [embed.title or "", embed.description or ""]
        + [field.name + "\n" + field.value for field in embed.fields]
    )

    assert field_names == {
        "Unresolved Matches",
        "Active Queues",
        "Active Matches",
        "Backlog",
        "Runtime",
        "Persistent Voice",
        "Schema",
    }
    assert "Staff review: **1**" in rendered_text
    assert "Ready Check: **1**" in rendered_text
    assert "Match #" not in rendered_text
    assert "/match force-result" not in rendered_text
    assert "/match force-close" not in rendered_text


def test_system_status_command_uses_admin_diagnostics_surface() -> None:
    source = inspect.getsource(HighlightBot._register_app_commands)

    assert '@admin_group.command(name="system-status"' in source
    assert '@admin_group.command(name="bot-voice-status"' in source
    assert "is_admin_member" in source
    assert "services.diagnostics.collect" in source
    assert "build_admin_diagnostics_embed" in source
    assert "ephemeral=True" in source
