from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RatingTierDefinition:
    code: str
    name: str
    min_rating: int
    max_rating: int | None
    accent_hex: str


@dataclass(slots=True)
class RatingChange:
    player_id: int
    before: int
    after: int
    delta: int


DEFAULT_TIERS = [
    RatingTierDefinition("bronze", "Bronze", 800, 899, "#7A5B3A"),
    RatingTierDefinition("silver", "Silver", 900, 999, "#A7B6C8"),
    RatingTierDefinition("gold", "Gold", 1000, 1099, "#D8A93B"),
    RatingTierDefinition("platinum", "Platinum", 1100, 1199, "#5DCBC8"),
    RatingTierDefinition("diamond", "Diamond", 1200, 1349, "#7CA8FF"),
    RatingTierDefinition("master", "Master", 1350, 1499, "#826BFF"),
    RatingTierDefinition("elite", "Elite", 1500, None, "#C85BFF"),
]


def expected_score(team_rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + 10 ** ((opponent_rating - team_rating) / 400))


def k_factor(matches_played: int) -> int:
    if matches_played < 20:
        return 40
    if matches_played < 100:
        return 32
    return 24


def calculate_delta(*, rating: int, matches_played: int, team_rating: float, opponent_rating: float, actual: float) -> int:
    del rating
    return round(k_factor(matches_played) * (actual - expected_score(team_rating, opponent_rating)))


def bounded_rating(before: int, delta: int, *, floor: int = 800) -> int:
    return max(floor, before + delta)


def soft_reset_seed(*, final_rank: int, total_players: int) -> int:
    if total_players <= 1:
        return 1000
    percentile = (final_rank - 1) / (total_players - 1)
    seeded = round(1100 - (percentile * 200))
    return max(900, min(1100, seeded))
