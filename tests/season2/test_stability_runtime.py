from __future__ import annotations

from contextlib import asynccontextmanager
import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.bot import HighlightBot
from highlight_manager.app.config import Settings
from highlight_manager.app.runtime import Repositories
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.legacy_runtime import clear_legacy_runtime_registry, get_legacy_runtime_summary
from highlight_manager.modules.common.enums import ActivityKind, MatchMode, RulesetKey, WalletTransactionType
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
from highlight_manager.modules.ranks.repository import RankRepository
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService
from highlight_manager.modules.shop.repository import ShopRepository
from highlight_manager.modules.shop.service import ShopService
from highlight_manager.modules.tournaments.repository import TournamentRepository
from highlight_manager.tasks.cleanup import CleanupWorker
from highlight_manager.tasks.recovery import RecoveryCoordinator


class NullLogger:
    def info(self, *_args, **_kwargs) -> None:
        return None

    def warning(self, *_args, **_kwargs) -> None:
        return None

    def exception(self, *_args, **_kwargs) -> None:
        return None


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'stability.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def build_services(settings: Settings) -> SimpleNamespace:
    guild_service = GuildService(settings)
    profile_service = ProfileService()
    season_service = SeasonService()
    rank_service = RankService()
    moderation_service = ModerationService()
    economy_service = EconomyService()
    return SimpleNamespace(
        guilds=guild_service,
        profiles=profile_service,
        seasons=season_service,
        ranks=rank_service,
        moderation=moderation_service,
        economy=economy_service,
        shop=ShopService(economy_service),
        matches=MatchService(
            settings,
            profile_service=profile_service,
            season_service=season_service,
            rank_service=rank_service,
            economy_service=economy_service,
            moderation_service=moderation_service,
        ),
    )


def build_repositories(session: AsyncSession) -> Repositories:
    return Repositories(
        session=session,
        guilds=GuildRepository(session),
        profiles=ProfileRepository(session),
        seasons=SeasonRepository(session),
        ranks=RankRepository(session),
        matches=MatchRepository(session),
        economy=EconomyRepository(session),
        shop=ShopRepository(session),
        tournaments=TournamentRepository(session),
        moderation=ModerationRepository(session),
    )


def build_fake_runtime(session: AsyncSession, settings: Settings):
    services = build_services(settings)

    class FakeRuntime:
        def __init__(self) -> None:
            self.services = services

        @asynccontextmanager
        async def session(self):
            yield build_repositories(session)

    return FakeRuntime(), services


@pytest.mark.asyncio
async def test_cleanup_worker_clears_orphaned_queue_activity(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    runtime, services = build_fake_runtime(session, settings)
    repos = build_repositories(session)

    bundle = await services.guilds.ensure_guild(repos.guilds, 9001, "Highlight")
    season = await services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
    player = await services.profiles.ensure_player(repos.profiles, bundle.guild.id, 900101, display_name="QueueUser")
    queue = await services.matches.create_queue(
        repos.matches,
        repos.profiles,
        repos.moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=player.id,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=555,
    )
    await services.matches.cancel_queue(
        repos.matches,
        repos.profiles,
        repos.moderation,
        queue_id=queue.queue.id,
        actor_player_id=player.id,
        reason="test_cancel",
    )
    await repos.profiles.set_activity(player.id, activity_kind=ActivityKind.QUEUE, queue_id=queue.queue.id)

    bot = SimpleNamespace(
        runtime=runtime,
        logger=NullLogger(),
        get_guild=lambda _guild_id: None,
    )
    worker = CleanupWorker()
    await worker.run(bot)

    activity = await repos.profiles.ensure_activity(player.id)
    assert activity.activity_kind == ActivityKind.IDLE
    assert worker.last_summary["cleared_orphaned_activities"] == 1


@pytest.mark.asyncio
async def test_cleanup_worker_reconciles_wallet_totals_from_ledger(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    runtime, services = build_fake_runtime(session, settings)
    repos = build_repositories(session)

    bundle = await services.guilds.ensure_guild(repos.guilds, 90011, "Highlight")
    player = await services.profiles.ensure_player(repos.profiles, bundle.guild.id, 900111, display_name="WalletUser")
    await services.economy.adjust_balance(
        repos.economy,
        player_id=player.id,
        amount=150,
        transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
        idempotency_key="wallet-seed",
        reason="seed",
    )
    await services.economy.adjust_balance(
        repos.economy,
        player_id=player.id,
        amount=-40,
        transaction_type=WalletTransactionType.PURCHASE,
        idempotency_key="wallet-spend",
        reason="spend",
    )
    wallet = await repos.economy.ensure_wallet(player.id)
    wallet.balance = 999
    wallet.lifetime_earned = 999
    wallet.lifetime_spent = 999
    await session.flush()

    bot = SimpleNamespace(
        runtime=runtime,
        logger=NullLogger(),
        get_guild=lambda _guild_id: None,
    )
    worker = CleanupWorker()
    await worker.run(bot)

    assert wallet.balance == 110
    assert wallet.lifetime_earned == 150
    assert wallet.lifetime_spent == 40
    assert worker.last_summary["reconciled_wallets"] == 1


@pytest.mark.asyncio
async def test_recovery_reports_missing_voice_dependency(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    runtime, services = build_fake_runtime(session, settings)
    repos = build_repositories(session)

    bundle = await services.guilds.ensure_guild(repos.guilds, 9002, "Highlight")
    await services.guilds.update_settings(
        repos.guilds,
        discord_guild_id=9002,
        guild_id=bundle.guild.id,
        persistent_voice_enabled=True,
        persistent_voice_channel_id=777777,
    )

    class FakeGuild:
        id = 9002

    recovery = RecoveryCoordinator()
    monkeypatch.setattr(recovery, "voice_dependency_available", lambda: False)
    bot = SimpleNamespace(
        runtime=runtime,
        guilds=[FakeGuild()],
        logger=NullLogger(),
    )

    await recovery.restore_persistent_voice(bot)
    status = recovery.get_voice_status(9002)

    assert status is not None
    assert status.state == "dependency_missing"
    assert status.retry_in_seconds == 15
    assert "PyNaCl" in (status.reason or "")


def test_legacy_runtime_imports_are_tracked() -> None:
    clear_legacy_runtime_registry()
    with pytest.warns(DeprecationWarning):
        services_module = importlib.import_module("highlight_manager.services")
        importlib.reload(services_module)
    with pytest.warns(DeprecationWarning):
        repositories_module = importlib.import_module("highlight_manager.repositories")
        importlib.reload(repositories_module)
    summary = get_legacy_runtime_summary()

    assert summary["legacy_import_count"] == 2
    assert "highlight_manager.services" in summary["legacy_packages"]
    assert "highlight_manager.repositories" in summary["legacy_packages"]
    clear_legacy_runtime_registry()


def test_build_rank_nickname_strips_existing_rank_prefixes() -> None:
    assert HighlightBot.build_rank_nickname(173, "Rank 373 ANAS") == "RANK 173 | ANAS"
    assert HighlightBot.build_rank_nickname(190, "Rank 76 Aniss") == "RANK 190 | Aniss"
    assert HighlightBot.build_rank_nickname(191, "RANK 191 | Rank 544 Soong7") == "RANK 191 | Soong7"


def test_pick_rank_source_name_prefers_clean_non_rank_text() -> None:
    fake_member = SimpleNamespace(
        nick="RANK 173 | Rank 373 ANAS",
        global_name="ANAS",
        name="anasboumine1161",
        display_name="RANK 173 | Rank 373 ANAS",
    )

    assert HighlightBot.pick_rank_source_name(fake_member) == "ANAS"


@pytest.mark.asyncio
async def test_restore_views_rebinds_queue_and_match_messages(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    runtime, services = build_fake_runtime(session, settings)
    repos = build_repositories(session)

    bundle = await services.guilds.ensure_guild(repos.guilds, 90022, "Highlight")
    season = await services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
    queue_creator = await services.profiles.ensure_player(repos.profiles, bundle.guild.id, 902201, display_name="QueueHost")
    active_queue = await services.matches.create_queue(
        repos.matches,
        repos.profiles,
        repos.moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=queue_creator.id,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=101,
    )
    await repos.matches.set_queue_public_message_id(active_queue.queue.id, 1001)

    player_one = await services.profiles.ensure_player(repos.profiles, bundle.guild.id, 902211, display_name="One")
    player_two = await services.profiles.ensure_player(repos.profiles, bundle.guild.id, 902212, display_name="Two")
    for player in [player_one, player_two]:
        await services.seasons.ensure_player(repos.seasons, season.id, player.id)
    ranked_queue = await services.matches.create_queue(
        repos.matches,
        repos.profiles,
        repos.moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=player_one.id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=202,
    )
    await repos.matches.set_queue_public_message_id(ranked_queue.queue.id, 2001)
    ranked_queue = await repos.matches.get_queue_snapshot(ranked_queue.queue.id, for_update=True)
    assert ranked_queue is not None
    match = await services.matches.join_queue(
        repos.matches,
        repos.profiles,
        repos.moderation,
        queue_id=ranked_queue.queue.id,
        player_id=player_two.id,
        team_number=2,
    )
    match = await services.matches.submit_room_info(
        repos.matches,
        repos.profiles,
        repos.moderation,
        queue_id=match.queue.id,
        submitter_player_id=player_one.id,
        is_moderator=False,
        room_code="ROOM-RESTORE",
        room_password="PW-RESTORE",
        room_notes=None,
    )
    match = await services.matches.mark_match_live(
        repos.matches,
        match_id=match.match.id,
        result_channel_id=3001,
        result_message_id=3002,
        team1_voice_channel_id=3003,
        team2_voice_channel_id=3004,
    )

    added_views: list[tuple[int, str]] = []

    class FakeBot:
        def __init__(self) -> None:
            self.runtime = runtime

        def add_view(self, view, *, message_id: int) -> None:
            added_views.append((message_id, type(view).__name__))

        def build_queue_view(self, queue_id, *, snapshot=None):
            assert snapshot is not None
            return SimpleNamespace(queue_id=queue_id)

        def build_match_view(self, match_id, *, snapshot=None):
            assert snapshot is not None
            return SimpleNamespace(match_id=match_id)

    recovery = RecoveryCoordinator()
    restored = await recovery.restore_views(FakeBot())

    assert restored == 3
    assert (1001, "SimpleNamespace") in added_views
    assert (2001, "SimpleNamespace") in added_views
    assert (3002, "SimpleNamespace") in added_views


@pytest.mark.asyncio
async def test_submit_vote_snapshot_stays_consistent_without_reload(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    services = build_services(settings)
    repos = build_repositories(session)

    bundle = await services.guilds.ensure_guild(repos.guilds, 9003, "Highlight")
    season = await services.seasons.ensure_active(repos.seasons, bundle.guild.id, bundle.settings)
    player_one = await services.profiles.ensure_player(repos.profiles, bundle.guild.id, 3001, display_name="One")
    player_two = await services.profiles.ensure_player(repos.profiles, bundle.guild.id, 3002, display_name="Two")
    for player in [player_one, player_two]:
        await services.seasons.ensure_player(repos.seasons, season.id, player.id)

    queue = await services.matches.create_queue(
        repos.matches,
        repos.profiles,
        repos.moderation,
        guild_id=bundle.guild.id,
        season_id=season.id,
        creator_player_id=player_one.id,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.ONE_V_ONE,
        source_channel_id=444,
    )
    await services.matches.join_queue(
        repos.matches,
        repos.profiles,
        repos.moderation,
        queue_id=queue.queue.id,
        player_id=player_two.id,
        team_number=2,
    )
    match = await services.matches.submit_room_info(
        repos.matches,
        repos.profiles,
        repos.moderation,
        queue_id=queue.queue.id,
        submitter_player_id=player_one.id,
        is_moderator=False,
        room_code="ROOM-3003",
        room_password="PW-3003",
        room_notes=None,
    )
    match = await services.matches.mark_match_live(
        repos.matches,
        match_id=match.match.id,
        result_channel_id=1,
        result_message_id=2,
        team1_voice_channel_id=3,
        team2_voice_channel_id=4,
    )

    after_first_vote = await services.matches.submit_vote(
        repos.matches,
        match_id=match.match.id,
        player_id=player_one.id,
        winner_team_number=1,
        winner_mvp_player_id=None,
        loser_mvp_player_id=None,
    )
    after_second_vote = await services.matches.submit_vote(
        repos.matches,
        match_id=match.match.id,
        player_id=player_two.id,
        winner_team_number=1,
        winner_mvp_player_id=None,
        loser_mvp_player_id=None,
    )

    assert len(after_first_vote.votes) == 1
    assert len(after_second_vote.votes) == 2
    assert after_second_vote.all_votes_match() is True
