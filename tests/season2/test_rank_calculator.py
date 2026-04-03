from highlight_manager.modules.ranks.calculator import bounded_rating, calculate_delta, expected_score, k_factor, soft_reset_seed


def test_expected_score_is_symmetric() -> None:
    left = expected_score(1000, 1100)
    right = expected_score(1100, 1000)
    assert round(left + right, 10) == 1.0


def test_k_factor_steps_down_over_time() -> None:
    assert k_factor(0) == 40
    assert k_factor(20) == 32
    assert k_factor(100) == 24


def test_bounded_rating_respects_floor() -> None:
    assert bounded_rating(805, -30) == 800


def test_soft_reset_seed_is_clamped() -> None:
    assert soft_reset_seed(final_rank=1, total_players=100) == 1100
    assert soft_reset_seed(final_rank=100, total_players=100) == 900


def test_calculate_delta_rewards_upset_win() -> None:
    underdog_delta = calculate_delta(
        rating=900,
        matches_played=10,
        team_rating=900,
        opponent_rating=1100,
        actual=1.0,
    )
    favorite_delta = calculate_delta(
        rating=1100,
        matches_played=10,
        team_rating=1100,
        opponent_rating=900,
        actual=1.0,
    )
    assert underdog_delta > favorite_delta
