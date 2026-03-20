from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.services.bootstrap_service import BootstrapService
from highlight_manager.services.rank_service import RankSyncResult


@dataclass
class FakeMember:
    id: int
    display_name: str
    joined_at: datetime
    bot: bool = False


@dataclass
class FakeGuild:
    members: list[FakeMember]


class DummyProfileService:
    pass


@pytest.mark.asyncio
async def test_bootstrap_preview_assigns_oldest_members_first() -> None:
    now = datetime.now(UTC)
    guild = FakeGuild(
        members=[
            FakeMember(id=1, display_name="OldGuard", joined_at=now - timedelta(days=200)),
            FakeMember(id=2, display_name="MidPlayer", joined_at=now - timedelta(days=65)),
            FakeMember(id=3, display_name="NewJoin", joined_at=now - timedelta(days=10)),
        ],
    )
    service = BootstrapService(DummyProfileService())  # type: ignore[arg-type]
    summary, preview = await service.preview(guild, GuildConfig(guild_id=1))

    assert summary.processed_members == 3
    assert summary.first_assigned_rank == 1
    assert summary.last_assigned_rank == 3
    assert preview[0].display_name == "OldGuard"
    assert preview[0].rank == 1
    assert preview[1].rank == 2
    assert preview[2].rank == 3
    assert all(entry.starting_points == 0 for entry in preview)


class FakeRepository:
    def __init__(self) -> None:
        self.saved_profiles: list[PlayerProfile] = []

    async def upsert(self, profile: PlayerProfile) -> PlayerProfile:
        self.saved_profiles.append(profile.model_copy(deep=True))
        return profile


class FakeRankService:
    async def sync_member_rank(self, member, profile, config) -> RankSyncResult:
        return RankSyncResult(
            nickname_attempted=True,
            nickname_failed=True,
            failure_category="hierarchy",
            skipped_reason="Skipped nickname update due to role hierarchy.",
        )


class FakeProfileService:
    def __init__(self) -> None:
        self.repository = FakeRepository()
        self.rank_service = FakeRankService()

    async def ensure_profile(self, guild, user_id: int, config, *, sync_identity: bool = True) -> PlayerProfile:
        return PlayerProfile(guild_id=guild.id, user_id=user_id)


@pytest.mark.asyncio
async def test_bootstrap_run_reports_rename_hierarchy_failures_explicitly() -> None:
    now = datetime.now(UTC)
    guild = FakeGuild(
        members=[FakeMember(id=1, display_name="OwnerLike", joined_at=now - timedelta(days=50))]
    )
    guild.id = 1  # type: ignore[attr-defined]
    for member in guild.members:
        member.guild = guild  # type: ignore[attr-defined]
    service = BootstrapService(FakeProfileService())  # type: ignore[arg-type]

    summary = await service.run(guild, GuildConfig(guild_id=1))

    assert summary.processed_members == 1
    assert summary.first_assigned_rank == 1
    assert summary.last_assigned_rank == 1
    assert summary.renamed_members == 0
    assert summary.rename_failures == 1
    assert summary.rename_skipped_due_to_hierarchy == 1
    assert summary.rename_skipped_due_to_missing_permission == 0
    assert summary.rename_skipped_other == 0


@pytest.mark.asyncio
async def test_bootstrap_run_resets_season_state_without_erasing_lifetime_totals() -> None:
    now = datetime.now(UTC)
    guild = FakeGuild(
        members=[FakeMember(id=1, display_name="Veteran", joined_at=now - timedelta(days=50))]
    )
    guild.id = 1  # type: ignore[attr-defined]
    for member in guild.members:
        member.guild = guild  # type: ignore[attr-defined]

    class PreservingProfileService(FakeProfileService):
        async def ensure_profile(self, guild, user_id: int, config, *, sync_identity: bool = True) -> PlayerProfile:
            profile = PlayerProfile(guild_id=guild.id, user_id=user_id, current_points=45, lifetime_points=200)
            profile.season_stats.wins = 9
            profile.season_stats.mvp_wins = 3
            profile.lifetime_stats.wins = 20
            return profile

    service = BootstrapService(PreservingProfileService())  # type: ignore[arg-type]

    await service.run(guild, GuildConfig(guild_id=1))
    saved = service.profile_service.repository.saved_profiles[0]

    assert saved.current_points == 0
    assert saved.season_stats.matches_played == 0
    assert saved.season_stats.wins == 0
    assert saved.season_stats.mvp_wins == 0
    assert saved.lifetime_points == 200
    assert saved.lifetime_stats.wins == 20
