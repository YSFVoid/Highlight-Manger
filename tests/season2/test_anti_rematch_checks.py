from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.models.competitive import RatingHistoryModel
from highlight_manager.db.models.economy import WalletTransactionModel
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import (
    MatchMode,
    MatchPlayerResult,
    MatchResultPhase,
    MatchState,
    RulesetKey,
)
from highlight_manager.modules.common.time import utcnow
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.service import MatchService
from highlight_manager.modules.matches.ui import build_match_review_inbox_embed
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.repository import RankRepository
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'anti-rematch.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class AntiRematchContext:
    session: AsyncSession
    guild_id: int
    season_id: int
    guilds: GuildRepository
    profiles: ProfileRepository
    seasons: SeasonRepository
    ranks: RankRepository
    matches: MatchRepository
    economy: EconomyRepository
    moderation: ModerationRepository
    guild_service: GuildService
    profile_service: ProfileService
    season_service: SeasonService
    match_service: MatchService
    next_discord_user_id: int = 40_000


async def _build_context(session: AsyncSession, *, discord_guild_id: int = 9601) -> AntiRematchContext:
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
    ranks = RankRepository(session)
    matches = MatchRepository(session)
    economy = EconomyRepository(session)
    moderation = ModerationRepository(session)
    bundle = await guild_service.ensure_guild(guilds, discord_guild_id, "Highlight")
    season = await season_service.ensure_active(seasons, bundle.guild.id, bundle.settings)
    return AntiRematchContext(
        session=session,
        guild_id=bundle.guild.id,
        season_id=season.id,
        guilds=guilds,
        profiles=profiles,
        seasons=seasons,
        ranks=ranks,
        matches=matches,
        economy=economy,
        moderation=moderation,
        guild_service=guild_service,
        profile_service=profile_service,
        season_service=season_service,
        match_service=match_service,
    )


async def _create_players(context: AntiRematchContext, count: int):
    players = []
    for _ in range(count):
        discord_user_id = context.next_discord_user_id
        context.next_discord_user_id += 1
        player = await context.profile_service.ensure_player(
            context.profiles,
            context.guild_id,
            discord_user_id,
            display_name=f"Player {discord_user_id}",
        )
        await context.season_service.ensure_player(context.seasons, context.season_id, player.id)
        players.append(player)
    return players


async def _mark_all_ready(context: AntiRematchContext, queue_id, player_ids: list[int]):
    snapshot = None
    for player_id in player_ids:
        snapshot = await context.match_service.mark_ready(
            context.matches,
            context.profiles,
            queue_id=queue_id,
            player_id=player_id,
        )
    assert snapshot is not None
    return snapshot


async def _create_live_match(
    context: AntiRematchContext,
    *,
    team1_players,
    team2_players,
    ruleset: RulesetKey = RulesetKey.HIGHLIGHT,
    mode: MatchMode = MatchMode.TWO_V_TWO,
):
    queue = await context.match_service.create_queue(
        context.matches,
        context.profiles,
        context.moderation,
        guild_id=context.guild_id,
        season_id=context.season_id,
        creator_player_id=team1_players[0].id,
        ruleset_key=ruleset,
        mode=mode,
        source_channel_id=777,
    )
    for player in team1_players[1:]:
        await context.match_service.join_queue(
            context.matches,
            context.profiles,
            context.moderation,
            queue_id=queue.queue.id,
            player_id=player.id,
            team_number=1,
        )
    for player in team2_players:
        await context.match_service.join_queue(
            context.matches,
            context.profiles,
            context.moderation,
            queue_id=queue.queue.id,
            player_id=player.id,
            team_number=2,
        )
    ready_queue = await _mark_all_ready(
        context,
        queue.queue.id,
        [player.id for player in [*team1_players, *team2_players]],
    )
    match = await context.match_service.submit_room_info(
        context.matches,
        context.profiles,
        context.moderation,
        queue_id=ready_queue.queue.id,
        submitter_player_id=team1_players[0].id,
        is_moderator=False,
        room_code=f"ROOM-{context.next_discord_user_id}",
        room_password="PW",
        room_notes=None,
    )
    return await context.match_service.mark_match_live(
        context.matches,
        match_id=match.match.id,
        result_channel_id=4_000 + match.match.match_number,
        result_message_id=5_000 + match.match.match_number,
        team1_voice_channel_id=6_000 + match.match.match_number,
        team2_voice_channel_id=7_000 + match.match.match_number,
    )


async def _confirm_match(
    context: AntiRematchContext,
    snapshot,
    *,
    winner_team_number: int = 1,
    source: str = "captain_consensus",
):
    winner_team = snapshot.team1_ids if winner_team_number == 1 else snapshot.team2_ids
    loser_team = snapshot.team2_ids if winner_team_number == 1 else snapshot.team1_ids
    return await context.match_service.confirm_match(
        context.matches,
        context.profiles,
        context.seasons,
        context.ranks,
        context.economy,
        context.moderation,
        match_id=snapshot.match.id,
        winner_team_number=winner_team_number,
        winner_mvp_player_id=winner_team[0],
        loser_mvp_player_id=loser_team[0],
        actor_player_id=winner_team[0],
        source=source,
    )


async def _set_confirmed_at(context: AntiRematchContext, snapshot, *, age_hours: int) -> None:
    timestamp = utcnow() - timedelta(hours=age_hours)
    snapshot.match.confirmed_at = timestamp
    snapshot.match.closed_at = timestamp
    await context.session.flush()


async def _count_rating_history_rows(context: AntiRematchContext, match_id) -> int:
    value = await context.session.scalar(
        select(func.count())
        .select_from(RatingHistoryModel)
        .where(RatingHistoryModel.match_id == match_id)
    )
    return int(value or 0)


async def _count_wallet_transactions(context: AntiRematchContext, match_id) -> int:
    value = await context.session.scalar(
        select(func.count())
        .select_from(WalletTransactionModel)
        .where(WalletTransactionModel.related_match_id == match_id)
    )
    return int(value or 0)


@pytest.mark.asyncio
async def test_third_exact_rematch_is_held_without_rewards_or_rating_history(session: AsyncSession) -> None:
    context = await _build_context(session)
    team1 = await _create_players(context, 2)
    team2 = await _create_players(context, 2)

    first = await _create_live_match(context, team1_players=team1, team2_players=team2)
    first = await _confirm_match(context, first)
    await _set_confirmed_at(context, first, age_hours=23)

    second = await _create_live_match(context, team1_players=team1, team2_players=team2)
    second = await _confirm_match(context, second)
    await _set_confirmed_at(context, second, age_hours=1)

    current = await _create_live_match(context, team1_players=team1, team2_players=team2)
    current = await _confirm_match(context, current)

    assert current.match.state == MatchState.RESULT_PENDING
    assert current.match.result_phase == MatchResultPhase.STAFF_REVIEW
    assert current.anti_rematch_decision is not None
    assert current.anti_rematch_decision.reason == "exact_repeat"
    assert current.anti_rematch_decision.prior_match_numbers == [
        first.match.match_number,
        second.match.match_number,
    ]
    assert await _count_rating_history_rows(context, current.match.id) == 0
    assert await _count_wallet_transactions(context, current.match.id) == 0
    assert all(row.rating_delta is None for row in current.players)
    assert all(row.coins_delta is None for row in current.players)
    assert all(row.result == MatchPlayerResult.NONE for row in current.players)

    audit = await context.moderation.get_match_anti_rematch_audit(current.match.id)
    assert audit is not None
    assert audit.metadata_json is not None
    assert audit.metadata_json["reason"] == "exact_repeat"
    assert audit.metadata_json["matched_prior_count"] == 2


@pytest.mark.asyncio
async def test_only_one_prior_exact_rematch_does_not_hold(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9602)
    team1 = await _create_players(context, 2)
    team2 = await _create_players(context, 2)

    first = await _create_live_match(context, team1_players=team1, team2_players=team2)
    first = await _confirm_match(context, first)
    await _set_confirmed_at(context, first, age_hours=2)

    current = await _create_live_match(context, team1_players=team1, team2_players=team2)
    current = await _confirm_match(context, current)

    assert current.match.state == MatchState.CONFIRMED
    assert current.anti_rematch_decision is None
    assert await _count_rating_history_rows(context, current.match.id) > 0
    assert await _count_wallet_transactions(context, current.match.id) > 0


@pytest.mark.asyncio
async def test_side_swapped_exact_rematches_count_toward_hold(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9603)
    team1 = await _create_players(context, 2)
    team2 = await _create_players(context, 2)

    first = await _create_live_match(context, team1_players=team1, team2_players=team2)
    first = await _confirm_match(context, first)
    await _set_confirmed_at(context, first, age_hours=23)

    second = await _create_live_match(context, team1_players=team2, team2_players=team1)
    second = await _confirm_match(context, second, winner_team_number=2)
    await _set_confirmed_at(context, second, age_hours=1)

    current = await _create_live_match(context, team1_players=team1, team2_players=team2)
    current = await _confirm_match(context, current)

    assert current.match.state == MatchState.RESULT_PENDING
    assert current.match.result_phase == MatchResultPhase.STAFF_REVIEW
    assert current.anti_rematch_decision is not None
    assert current.anti_rematch_decision.reason == "exact_repeat"


@pytest.mark.asyncio
async def test_high_overlap_rematch_at_threshold_is_held(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9604)
    team1_current = await _create_players(context, 4)
    team2_current = await _create_players(context, 4)
    extra = await _create_players(context, 4)

    first = await _create_live_match(
        context,
        team1_players=[team1_current[0], team1_current[1], team1_current[2], extra[0]],
        team2_players=[team2_current[0], team2_current[1], team2_current[2], extra[1]],
        mode=MatchMode.FOUR_V_FOUR,
    )
    first = await _confirm_match(context, first)
    await _set_confirmed_at(context, first, age_hours=23)

    second = await _create_live_match(
        context,
        team1_players=[team1_current[0], team1_current[1], team1_current[2], extra[2]],
        team2_players=[team2_current[0], team2_current[1], team2_current[2], extra[3]],
        mode=MatchMode.FOUR_V_FOUR,
    )
    second = await _confirm_match(context, second)
    await _set_confirmed_at(context, second, age_hours=1)

    current = await _create_live_match(
        context,
        team1_players=team1_current,
        team2_players=team2_current,
        mode=MatchMode.FOUR_V_FOUR,
    )
    current = await _confirm_match(context, current)

    assert current.match.state == MatchState.RESULT_PENDING
    assert current.match.result_phase == MatchResultPhase.STAFF_REVIEW
    assert current.anti_rematch_decision is not None
    assert current.anti_rematch_decision.reason == "high_overlap_repeat"
    assert current.anti_rematch_decision.overlap_threshold == 3
    assert current.anti_rematch_decision.best_overlap_team1 == 3
    assert current.anti_rematch_decision.best_overlap_team2 == 3


@pytest.mark.asyncio
async def test_non_matching_candidates_and_old_matches_are_ignored(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9605)
    team1 = await _create_players(context, 4)
    team2 = await _create_players(context, 4)
    extras = await _create_players(context, 6)

    valid = await _create_live_match(
        context,
        team1_players=team1,
        team2_players=team2,
        mode=MatchMode.FOUR_V_FOUR,
    )
    valid = await _confirm_match(context, valid)
    await _set_confirmed_at(context, valid, age_hours=2)

    low_overlap = await _create_live_match(
        context,
        team1_players=[team1[0], team1[1], extras[0], extras[1]],
        team2_players=[team2[0], team2[1], team2[2], team2[3]],
        mode=MatchMode.FOUR_V_FOUR,
    )
    low_overlap = await _confirm_match(context, low_overlap)
    await _set_confirmed_at(context, low_overlap, age_hours=3)

    different_ruleset = await _create_live_match(
        context,
        team1_players=team1,
        team2_players=team2,
        mode=MatchMode.FOUR_V_FOUR,
        ruleset=RulesetKey.APOSTADO,
    )
    different_ruleset = await _confirm_match(context, different_ruleset)
    await _set_confirmed_at(context, different_ruleset, age_hours=4)

    old_match = await _create_live_match(
        context,
        team1_players=team1,
        team2_players=team2,
        mode=MatchMode.FOUR_V_FOUR,
    )
    old_match = await _confirm_match(context, old_match)
    await _set_confirmed_at(context, old_match, age_hours=25)

    current = await _create_live_match(
        context,
        team1_players=team1,
        team2_players=team2,
        mode=MatchMode.FOUR_V_FOUR,
    )
    current = await _confirm_match(context, current)

    assert current.match.state == MatchState.CONFIRMED
    assert current.anti_rematch_decision is None


@pytest.mark.asyncio
async def test_force_result_bypasses_anti_rematch_hold(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9606)
    team1 = await _create_players(context, 2)
    team2 = await _create_players(context, 2)

    first = await _create_live_match(context, team1_players=team1, team2_players=team2)
    first = await _confirm_match(context, first)
    await _set_confirmed_at(context, first, age_hours=23)

    second = await _create_live_match(context, team1_players=team1, team2_players=team2)
    second = await _confirm_match(context, second)
    await _set_confirmed_at(context, second, age_hours=1)

    current = await _create_live_match(context, team1_players=team1, team2_players=team2)
    current = await _confirm_match(context, current, source="force_result")

    assert current.match.state == MatchState.CONFIRMED
    assert current.anti_rematch_decision is None
    assert await context.moderation.get_match_anti_rematch_audit(current.match.id) is None


@pytest.mark.asyncio
async def test_review_inbox_shows_suspicious_rematch_detail_and_counts_staff_review(session: AsyncSession) -> None:
    context = await _build_context(session, discord_guild_id=9607)
    team1 = await _create_players(context, 2)
    team2 = await _create_players(context, 2)

    first = await _create_live_match(context, team1_players=team1, team2_players=team2)
    first = await _confirm_match(context, first)
    await _set_confirmed_at(context, first, age_hours=23)

    second = await _create_live_match(context, team1_players=team1, team2_players=team2)
    second = await _confirm_match(context, second)
    await _set_confirmed_at(context, second, age_hours=1)

    current = await _create_live_match(context, team1_players=team1, team2_players=team2)
    current = await _confirm_match(context, current)

    items = await context.match_service.list_review_inbox(
        context.matches,
        context.moderation,
        guild_id=context.guild_id,
        now=utcnow(),
        limit=10,
    )
    counts = await context.match_service.count_review_inbox_by_reason(
        context.matches,
        guild_id=context.guild_id,
        now=utcnow(),
    )

    assert len(items) == 1
    assert items[0].reason == "staff_review"
    assert items[0].reason_label == "Suspicious rematch"
    assert items[0].staff_detail is not None
    assert f"#{first.match.match_number:03d}" in items[0].staff_detail
    assert f"#{second.match.match_number:03d}" in items[0].staff_detail
    assert counts["staff_review"] == 1

    embed = build_match_review_inbox_embed(items)
    assert "Suspicious rematch" in embed.fields[0].name
    assert "Prior similar matches:" in embed.fields[0].value
