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
from highlight_manager.db.models.competitive import MatchModel
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import MatchMode, MatchResultPhase, MatchState, RulesetKey
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.matches.types import MatchSnapshot
from highlight_manager.modules.matches.ui import build_match_review_inbox_embed
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'review-inbox.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class ReviewInboxContext:
    session: AsyncSession
    settings: Settings
    guild_id: int
    season_id: int
    guilds: GuildRepository
    profiles: ProfileRepository
    seasons: SeasonRepository
    matches: MatchRepository
    moderation: ModerationRepository
    guild_service: GuildService
    profile_service: ProfileService
    season_service: SeasonService
    match_service: MatchService
    next_discord_user_id: int = 10_000


async def _build_context(session: AsyncSession, *, discord_guild_id: int = 9001) -> ReviewInboxContext:
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
    return ReviewInboxContext(
        session=session,
        settings=settings,
        guild_id=bundle.guild.id,
        season_id=season.id,
        guilds=guilds,
        profiles=profiles,
        seasons=seasons,
        matches=matches,
        moderation=moderation,
        guild_service=guild_service,
        profile_service=profile_service,
        season_service=season_service,
        match_service=match_service,
    )


async def _mark_all_ready(context: ReviewInboxContext, snapshot) -> None:
    for row in snapshot.players:
        await context.match_service.mark_ready(
            context.matches,
            context.profiles,
            queue_id=snapshot.queue.id,
            player_id=row.player_id,
        )


async def _create_live_match(context: ReviewInboxContext) -> MatchSnapshot:
    players = []
    for index in range(4):
        discord_user_id = context.next_discord_user_id + index
        players.append(
            await context.profile_service.ensure_player(
                context.profiles,
                context.guild_id,
                discord_user_id,
                display_name=f"Player {discord_user_id}",
            )
        )
    context.next_discord_user_id += 4

    queue = await context.match_service.create_queue(
        context.matches,
        context.profiles,
        context.moderation,
        guild_id=context.guild_id,
        season_id=context.season_id,
        creator_player_id=players[0].id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.TWO_V_TWO,
        source_channel_id=777,
    )
    await context.match_service.join_queue(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=queue.queue.id,
        player_id=players[1].id,
        team_number=1,
    )
    await context.match_service.join_queue(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=queue.queue.id,
        player_id=players[2].id,
        team_number=2,
    )
    ready_check = await context.match_service.join_queue(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=queue.queue.id,
        player_id=players[3].id,
        team_number=2,
    )
    await _mark_all_ready(context, ready_check)
    match = await context.match_service.submit_room_info(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=queue.queue.id,
        submitter_player_id=players[0].id,
        is_moderator=False,
        room_code=f"ROOM-{context.next_discord_user_id}",
        room_password="PW",
        room_notes=None,
    )
    return await context.match_service.mark_match_live(
        context.matches,
        match_id=match.match.id,
        result_channel_id=5_500 + match.match.match_number,
        result_message_id=6_500 + match.match.match_number,
        team1_voice_channel_id=7_500 + match.match.match_number,
        team2_voice_channel_id=8_500 + match.match.match_number,
    )


async def _refresh(context: ReviewInboxContext, match: MatchModel) -> MatchSnapshot:
    await context.session.flush()
    snapshot = await context.matches.get_match_snapshot(match.id)
    assert snapshot is not None
    return snapshot


async def _set_terminal_state(
    context: ReviewInboxContext,
    *,
    state: MatchState,
    now: datetime,
) -> MatchSnapshot:
    snapshot = await _create_live_match(context)
    snapshot.match.state = state
    snapshot.match.result_phase = MatchResultPhase.STAFF_REVIEW
    snapshot.match.result_deadline_at = now - timedelta(minutes=30)
    snapshot.match.closed_at = now - timedelta(minutes=20)
    return await _refresh(context, snapshot.match)


@pytest.mark.asyncio
async def test_review_inbox_classifies_unresolved_matches(session: AsyncSession) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    context = await _build_context(session)

    expired = await _create_live_match(context)
    expired.match.state = MatchState.EXPIRED
    expired.match.result_phase = MatchResultPhase.STAFF_REVIEW
    expired.match.result_deadline_at = now - timedelta(minutes=40)
    expired.match.closed_at = now - timedelta(minutes=30)
    await _refresh(context, expired.match)

    staff_review = await _create_live_match(context)
    staff_review.match.state = MatchState.RESULT_PENDING
    staff_review.match.result_phase = MatchResultPhase.STAFF_REVIEW
    staff_review.match.result_deadline_at = now + timedelta(minutes=30)
    await _refresh(context, staff_review.match)

    overdue = await _create_live_match(context)
    overdue.match.state = MatchState.LIVE
    overdue.match.result_phase = MatchResultPhase.CAPTAIN
    overdue.match.captain_deadline_at = now - timedelta(minutes=5)
    overdue.match.result_deadline_at = now + timedelta(minutes=30)
    await _refresh(context, overdue.match)

    disputed = await _create_live_match(context)
    disputed.match.state = MatchState.RESULT_PENDING
    disputed.match.result_phase = MatchResultPhase.FALLBACK
    disputed.match.fallback_deadline_at = now + timedelta(minutes=30)
    disputed.match.result_deadline_at = now + timedelta(minutes=30)
    disputed = await _refresh(context, disputed.match)
    await context.matches.create_vote(
        match_id=disputed.match.id,
        player_id=disputed.players[0].player_id,
        winner_team_number=1,
        winner_mvp_player_id=disputed.players[0].player_id,
        loser_mvp_player_id=disputed.players[2].player_id,
    )
    await context.matches.create_vote(
        match_id=disputed.match.id,
        player_id=disputed.players[1].player_id,
        winner_team_number=2,
        winner_mvp_player_id=disputed.players[2].player_id,
        loser_mvp_player_id=disputed.players[0].player_id,
    )

    confirmed = await _set_terminal_state(context, state=MatchState.CONFIRMED, now=now)
    cancelled = await _set_terminal_state(context, state=MatchState.CANCELLED, now=now)
    force_closed = await _set_terminal_state(context, state=MatchState.FORCE_CLOSED, now=now)

    candidates = await context.matches.list_review_inbox_candidates(
        context.guild_id,
        now=now,
        limit=25,
    )
    candidate_numbers = {candidate.match_number for candidate in candidates}
    assert expired.match.match_number in candidate_numbers
    assert staff_review.match.match_number in candidate_numbers
    assert overdue.match.match_number in candidate_numbers
    assert disputed.match.match_number in candidate_numbers
    assert confirmed.match.match_number not in candidate_numbers
    assert cancelled.match.match_number not in candidate_numbers
    assert force_closed.match.match_number not in candidate_numbers

    items = await context.match_service.list_review_inbox(
        context.matches,
        context.moderation,
        guild_id=context.guild_id,
        now=now,
        limit=10,
    )

    assert [item.reason for item in items] == [
        "staff_review",
        "staff_review",
        "overdue",
        "disputed",
    ]
    assert [item.snapshot.match.match_number for item in items] == [
        expired.match.match_number,
        staff_review.match.match_number,
        overdue.match.match_number,
        disputed.match.match_number,
    ]


@pytest.mark.asyncio
async def test_review_inbox_ignores_incomplete_or_matching_votes(session: AsyncSession) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    context = await _build_context(session, discord_guild_id=9002)

    single_vote = await _create_live_match(context)
    single_vote.match.state = MatchState.RESULT_PENDING
    single_vote.match.result_phase = MatchResultPhase.FALLBACK
    single_vote.match.fallback_deadline_at = now + timedelta(minutes=30)
    single_vote.match.result_deadline_at = now + timedelta(minutes=30)
    single_vote = await _refresh(context, single_vote.match)
    await context.matches.create_vote(
        match_id=single_vote.match.id,
        player_id=single_vote.players[0].player_id,
        winner_team_number=1,
        winner_mvp_player_id=None,
        loser_mvp_player_id=None,
    )

    matching_votes = await _create_live_match(context)
    matching_votes.match.state = MatchState.RESULT_PENDING
    matching_votes.match.result_phase = MatchResultPhase.FALLBACK
    matching_votes.match.fallback_deadline_at = now + timedelta(minutes=30)
    matching_votes.match.result_deadline_at = now + timedelta(minutes=30)
    matching_votes = await _refresh(context, matching_votes.match)
    for voter in matching_votes.players[:2]:
        await context.matches.create_vote(
            match_id=matching_votes.match.id,
            player_id=voter.player_id,
            winner_team_number=1,
            winner_mvp_player_id=None,
            loser_mvp_player_id=None,
        )

    items = await context.match_service.list_review_inbox(
        context.matches,
        context.moderation,
        guild_id=context.guild_id,
        now=now,
        limit=10,
    )

    assert items == []


@pytest.mark.asyncio
async def test_review_inbox_embed_renders_empty_and_populated_states(session: AsyncSession) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    context = await _build_context(session, discord_guild_id=9003)

    empty_embed = build_match_review_inbox_embed([])
    assert empty_embed.title == "Unresolved Match Review Inbox"
    assert empty_embed.description == "No unresolved matches need staff review right now."

    overdue = await _create_live_match(context)
    overdue.match.state = MatchState.LIVE
    overdue.match.result_phase = MatchResultPhase.CAPTAIN
    overdue.match.captain_deadline_at = now - timedelta(minutes=5)
    overdue.match.result_deadline_at = now + timedelta(minutes=30)
    await _refresh(context, overdue.match)

    items = await context.match_service.list_review_inbox(
        context.matches,
        context.moderation,
        guild_id=context.guild_id,
        now=now,
        limit=10,
    )
    embed = build_match_review_inbox_embed(items, limit=1)

    assert len(embed.fields) == 1
    field = embed.fields[0]
    assert f"Match #{overdue.match.match_number:03d}" in field.name
    assert "Overdue" in field.name
    assert "Highlight 2V2" in field.value
    assert "Captain" in field.value
    assert "Votes: `0/2`" in field.value
    assert f"<#{overdue.match.result_channel_id}>" in field.value
    assert f"/match force-result match_number:{overdue.match.match_number}" in field.value
    assert f"/match force-close match_number:{overdue.match.match_number}" in field.value


def test_review_inbox_command_surface_is_registered() -> None:
    source = inspect.getsource(HighlightBot._register_app_commands)

    assert '@match_group.command(name="review-inbox"' in source
    assert "is_staff_member" in source
    assert "list_review_inbox" in source
    assert "build_match_review_inbox_embed" in source
    assert "ephemeral=True" in source
