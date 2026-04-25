from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.bot import HighlightBot
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.models.competitive import MatchModel, MatchPlayerModel
from highlight_manager.db.models.moderation import AuditLogModel
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import (
    AuditAction,
    AuditEntityType,
    MatchMode,
    MatchResultPhase,
    MatchState,
    RulesetKey,
)
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.matches.types import MatchRoomUpdateHistoryItem, MatchSnapshot
from highlight_manager.modules.matches.ui import build_match_rehost_history_embed
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'rehost-history.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class RehostHistoryContext:
    session: AsyncSession
    guild_id: int
    season_id: int
    profiles: ProfileRepository
    matches: MatchRepository
    moderation: ModerationRepository
    profile_service: ProfileService
    match_service: MatchService
    next_discord_user_id: int = 30_000


async def _build_context(session: AsyncSession, *, discord_guild_id: int = 9301) -> RehostHistoryContext:
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
    return RehostHistoryContext(
        session=session,
        guild_id=bundle.guild.id,
        season_id=season.id,
        profiles=profiles,
        matches=matches,
        moderation=moderation,
        profile_service=profile_service,
        match_service=match_service,
    )


async def _create_players(context: RehostHistoryContext, count: int):
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


async def _create_live_match(context: RehostHistoryContext):
    players = await _create_players(context, 2)
    queue = await context.match_service.create_queue(
        context.matches,
        context.profiles,
        context.moderation,
        guild_id=context.guild_id,
        season_id=context.season_id,
        creator_player_id=players[0].id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=777,
    )
    await context.match_service.join_queue(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=queue.queue.id,
        player_id=players[1].id,
        team_number=2,
    )
    for player in players:
        await context.match_service.mark_ready(
            context.matches,
            context.profiles,
            queue_id=queue.queue.id,
            player_id=player.id,
        )
    match = await context.match_service.submit_room_info(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=queue.queue.id,
        submitter_player_id=players[0].id,
        is_moderator=False,
        room_code="ROOM-OLD",
        room_password="PW-OLD",
        room_notes=None,
    )
    live_match = await context.match_service.mark_match_live(
        context.matches,
        match_id=match.match.id,
        result_channel_id=81,
        result_message_id=82,
        team1_voice_channel_id=83,
        team2_voice_channel_id=84,
    )
    return live_match, players


@pytest.mark.asyncio
async def test_update_room_info_records_rehost_audit_metadata(session: AsyncSession) -> None:
    context = await _build_context(session)
    live_match, players = await _create_live_match(context)

    updated = await context.match_service.update_room_info(
        context.matches,
        context.moderation,
        match_id=live_match.match.id,
        creator_player_id=players[0].id,
        room_code="ROOM-NEW",
        room_password="PW-NEW",
        room_notes="KEY-NEW",
    )

    assert updated.match.room_code == "ROOM-NEW"
    assert updated.match.room_password == "PW-NEW"
    assert updated.match.room_notes == "KEY-NEW"
    assert updated.match.rehost_count == 1

    audit = await context.session.scalar(
        select(AuditLogModel)
        .where(
            AuditLogModel.entity_id == str(live_match.match.id),
            AuditLogModel.action == AuditAction.MATCH_REHOSTED,
        )
        .order_by(AuditLogModel.id.desc())
    )

    assert audit is not None
    assert audit.actor_player_id == players[0].id
    assert audit.metadata_json == {
        "before_room_code": "ROOM-OLD",
        "before_room_password": "PW-OLD",
        "before_room_notes": None,
        "after_room_code": "ROOM-NEW",
        "after_room_password": "PW-NEW",
        "after_room_notes": "KEY-NEW",
        "rehost_count_before": 0,
        "rehost_count_after": 1,
    }


@pytest.mark.asyncio
async def test_list_room_update_history_returns_structured_items_and_legacy_entries(session: AsyncSession) -> None:
    context = await _build_context(session)
    live_match, players = await _create_live_match(context)
    legacy_time = datetime(2026, 1, 1, tzinfo=UTC)

    await context.moderation.create_audit(
        guild_id=context.guild_id,
        actor_player_id=players[0].id,
        entity_type=AuditEntityType.MATCH,
        entity_id=str(live_match.match.id),
        action=AuditAction.MATCH_REHOSTED,
        metadata_json=None,
        created_at=legacy_time,
    )
    await context.match_service.update_room_info(
        context.matches,
        context.moderation,
        match_id=live_match.match.id,
        creator_player_id=players[0].id,
        room_code="ROOM-NEW",
        room_password="PW-NEW",
        room_notes="KEY-NEW",
    )

    items = await context.match_service.list_room_update_history(
        context.matches,
        context.moderation,
        match_id=live_match.match.id,
    )

    assert len(items) == 2
    assert items[0].legacy is True
    assert items[0].actor_player_id == players[0].id
    assert items[0].actor_discord_id == players[0].discord_user_id
    assert items[0].created_at.replace(tzinfo=UTC) == legacy_time

    assert items[1].legacy is False
    assert items[1].actor_player_id == players[0].id
    assert items[1].actor_discord_id == players[0].discord_user_id
    assert items[1].before_room_code == "ROOM-OLD"
    assert items[1].before_room_password == "PW-OLD"
    assert items[1].before_room_notes is None
    assert items[1].after_room_code == "ROOM-NEW"
    assert items[1].after_room_password == "PW-NEW"
    assert items[1].after_room_notes == "KEY-NEW"
    assert items[1].rehost_count_before == 0
    assert items[1].rehost_count_after == 1


def test_match_rehost_history_embed_renders_empty_and_populated_states() -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    match = MatchModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        queue_id=uuid4(),
        match_number=22,
        creator_player_id=1,
        team1_captain_player_id=1,
        team2_captain_player_id=2,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.ONE_V_ONE,
        state=MatchState.LIVE,
        result_phase=MatchResultPhase.CAPTAIN,
        team_size=1,
        room_code="ROOM-CURRENT",
        room_password="PW-CURRENT",
        room_notes="KEY-CURRENT",
        result_channel_id=91,
        captain_deadline_at=now + timedelta(minutes=3),
        fallback_deadline_at=now + timedelta(minutes=10),
        result_deadline_at=now + timedelta(minutes=10),
        rehost_count=1,
    )
    snapshot = MatchSnapshot(
        match=match,
        players=[
            MatchPlayerModel(match_id=match.id, player_id=1, team_number=1),
            MatchPlayerModel(match_id=match.id, player_id=2, team_number=2),
        ],
        votes=[],
        player_discord_ids={1: 101, 2: 102},
    )

    empty_embed = build_match_rehost_history_embed(snapshot, [])
    assert empty_embed.title == "Match Rehost History - Match #022"
    assert empty_embed.description is not None
    assert "Highlight" in empty_embed.description
    assert "1V1" in empty_embed.description
    assert "No room-info edits have been recorded for this match." in empty_embed.fields[0].value

    items = [
        MatchRoomUpdateHistoryItem(
            actor_player_id=1,
            actor_discord_id=101,
            created_at=now - timedelta(minutes=30),
            before_room_code=None,
            before_room_password=None,
            before_room_notes=None,
            after_room_code=None,
            after_room_password=None,
            after_room_notes=None,
            rehost_count_before=None,
            rehost_count_after=None,
            legacy=True,
        ),
        MatchRoomUpdateHistoryItem(
            actor_player_id=1,
            actor_discord_id=101,
            created_at=now - timedelta(minutes=10),
            before_room_code="ROOM-OLD",
            before_room_password="PW-OLD",
            before_room_notes=None,
            after_room_code="ROOM-NEW",
            after_room_password="PW-NEW",
            after_room_notes="KEY-NEW",
            rehost_count_before=0,
            rehost_count_after=1,
            legacy=False,
        ),
    ]
    embed = build_match_rehost_history_embed(snapshot, items)

    assert len(embed.fields) == 2
    assert embed.fields[0].name.startswith("Edit 1 - <t:")
    assert "Detailed room changes were not recorded for this older update." in embed.fields[0].value
    assert embed.fields[1].name.startswith("Edit 2 - <t:")
    assert "Actor: <@101>" in embed.fields[1].value
    assert "Rehost count: `0 -> 1`" in embed.fields[1].value
    assert "ROOM-OLD" in embed.fields[1].value
    assert "PW-NEW" in embed.fields[1].value
    assert "KEY-NEW" in embed.fields[1].value


def test_rehost_history_command_surface_is_registered() -> None:
    source = inspect.getsource(HighlightBot._register_app_commands)

    assert '@match_group.command(name="rehost-history"' in source
    assert "is_staff_member" in source
    assert "get_match_by_number" in source
    assert "list_room_update_history" in source
    assert "build_match_rehost_history_embed" in source
    assert "ephemeral=True" in source
