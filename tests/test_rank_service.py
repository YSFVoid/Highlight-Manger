from datetime import UTC, datetime, timedelta

from highlight_manager.models.profile import PlayerProfile
from highlight_manager.services.rank_service import RankService


def test_sort_profiles_for_ranking_uses_points_wins_mvp_joined_at_and_user_id() -> None:
    service = RankService()
    now = datetime.now(UTC)
    profiles = [
        PlayerProfile(guild_id=1, user_id=3, current_points=200, joined_at=now - timedelta(days=10)),
        PlayerProfile(guild_id=1, user_id=1, current_points=200, joined_at=now - timedelta(days=20)),
        PlayerProfile(guild_id=1, user_id=2, current_points=200, joined_at=now - timedelta(days=20)),
        PlayerProfile(guild_id=1, user_id=4, current_points=250, joined_at=now - timedelta(days=5)),
    ]
    profiles[1].season_stats.wins = 3
    profiles[2].season_stats.wins = 3
    profiles[2].season_stats.mvp_wins = 2
    profiles[3].season_stats.wins = 1

    ordered = service.sort_profiles_for_ranking(profiles)

    assert [profile.user_id for profile in ordered] == [4, 2, 1, 3]


def test_rank_prefix_is_replaced_cleanly() -> None:
    service = RankService()
    assert service.strip_rank_prefix("Rank 3 Shadow") == "Shadow"
    assert service.strip_rank_prefix("RANK 44 | Shadow") == "Shadow"
    assert service.build_rank_nickname(120, service.strip_rank_prefix("Rank 3 Shadow")) == "RANK 120 | Shadow"
