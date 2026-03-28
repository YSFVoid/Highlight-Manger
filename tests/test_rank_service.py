from datetime import UTC, datetime

from highlight_manager.models.guild_config import default_rank_thresholds
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.services.rank_service import RankService


def test_negative_points_resolve_to_lowest_public_rank() -> None:
    service = RankService()
    assert service.resolve_rank(-50, default_rank_thresholds()) == 1


def test_high_points_resolve_to_top_rank() -> None:
    service = RankService()
    assert service.resolve_rank(920, default_rank_thresholds()) == 5


def test_rank_prefix_is_replaced_cleanly() -> None:
    service = RankService()
    assert service.strip_rank_prefix("Rank 3 Shadow") == "Shadow"
    assert service.build_rank_nickname(5, service.strip_rank_prefix("Rank 3 Shadow")) == "RANK 5 | Shadow"


def test_rank_prefix_strips_legacy_high_format_cleanly() -> None:
    service = RankService()
    assert service.strip_rank_prefix("RANK 621|HIGH Asta") == "Asta"
    assert service.strip_rank_prefix("Rank 1 HIGH SUNNLESS") == "SUNNLESS"
    assert service.strip_rank_prefix("HIGH Ahmed") == "Ahmed"


def test_assign_live_ranks_uses_points_then_wins_then_mvp_then_join_date_then_user_id() -> None:
    service = RankService()
    profiles = [
        PlayerProfile(guild_id=1, user_id=30, current_points=100, server_joined_at=datetime(2026, 1, 3, tzinfo=UTC)),
        PlayerProfile(guild_id=1, user_id=20, current_points=100, server_joined_at=datetime(2026, 1, 2, tzinfo=UTC)),
        PlayerProfile(guild_id=1, user_id=10, current_points=120),
    ]
    profiles[0].season_stats.wins = 1
    profiles[1].season_stats.wins = 3
    live_ranks = service.assign_live_ranks(profiles)

    assert live_ranks == {10: 1, 20: 2, 30: 3}


def test_assign_live_ranks_ignores_rank0_profiles() -> None:
    service = RankService()
    profiles = [
        PlayerProfile(guild_id=1, user_id=10, current_points=200, rank0=True),
        PlayerProfile(guild_id=1, user_id=20, current_points=150),
        PlayerProfile(guild_id=1, user_id=30, current_points=100),
    ]

    live_ranks = service.assign_live_ranks(profiles)

    assert live_ranks == {20: 1, 30: 2}
