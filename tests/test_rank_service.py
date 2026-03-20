from highlight_manager.models.guild_config import default_rank_thresholds
from highlight_manager.services.rank_service import RankService


def test_negative_points_resolve_to_lowest_public_rank() -> None:
    service = RankService()
    assert service.resolve_rank(-50, default_rank_thresholds()) == 1


def test_high_points_resolve_to_top_rank() -> None:
    service = RankService()
    assert service.resolve_rank(1300, default_rank_thresholds()) == 10


def test_rank_prefix_is_replaced_cleanly() -> None:
    service = RankService()
    assert service.strip_rank_prefix("Rank 3 Shadow") == "Shadow"
    assert service.build_rank_nickname(10, service.strip_rank_prefix("Rank 3 Shadow")) == "Rank 10 Shadow"
