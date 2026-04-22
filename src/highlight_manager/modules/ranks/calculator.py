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
    tier_before: str | None = None
    tier_after: str | None = None


DEFAULT_TIERS = [
    RatingTierDefinition("bronze", "Bronze", 800, 899, "#7A5B3A"),
    RatingTierDefinition("silver", "Silver", 900, 999, "#A7B6C8"),
    RatingTierDefinition("gold", "Gold", 1000, 1099, "#D8A93B"),
    RatingTierDefinition("platinum", "Platinum", 1100, 1199, "#5DCBC8"),
    RatingTierDefinition("diamond", "Diamond", 1200, 1349, "#7CA8FF"),
    RatingTierDefinition("master", "Master", 1350, 1499, "#826BFF"),
    RatingTierDefinition("elite", "Elite", 1500, None, "#C85BFF"),
]

TIER_EMOJI = {
    "bronze": "🟤",
    "silver": "⚪",
    "gold": "🟡",
    "platinum": "🔵",
    "diamond": "💎",
    "master": "🟣",
    "elite": "👑",
}

TIER_COLORS_RGB = {
    "bronze": (122, 91, 58),
    "silver": (167, 182, 200),
    "gold": (216, 169, 59),
    "platinum": (93, 203, 200),
    "diamond": (124, 168, 255),
    "master": (130, 107, 255),
    "elite": (200, 91, 255),
}


def resolve_tier(rating: int, tiers: list[RatingTierDefinition] | None = None) -> RatingTierDefinition:
    """Return the tier definition that contains the given rating."""
    for tier in reversed(tiers or DEFAULT_TIERS):
        if rating >= tier.min_rating:
            return tier
    return (tiers or DEFAULT_TIERS)[0]


def tier_emoji(code: str) -> str:
    """Return the emoji for a tier code."""
    return TIER_EMOJI.get(code, "⬜")


def tier_progress(rating: int, tiers: list[RatingTierDefinition] | None = None) -> tuple[int, int, int]:
    """Return (current_points_into_tier, points_needed_for_next, percentage)."""
    tier = resolve_tier(rating, tiers)
    if tier.max_rating is None:
        return 0, 0, 100
    points_into = rating - tier.min_rating
    range_size = tier.max_rating - tier.min_rating + 1
    pct = int(points_into / range_size * 100)
    return points_into, range_size, min(pct, 100)


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


def calculate_decay(days_inactive: int, current_rating: int, *, floor: int = 800, grace_days: int = 7, daily_loss: int = 5, max_loss: int = 100) -> int:
    """Calculate rating decay for inactivity. Returns the amount to subtract (positive number)."""
    if days_inactive <= grace_days:
        return 0
    decay_days = days_inactive - grace_days
    total_loss = min(decay_days * daily_loss, max_loss)
    # Don't decay below the floor
    max_possible = max(current_rating - floor, 0)
    return min(total_loss, max_possible)


def soft_reset_seed(*, final_rank: int, total_players: int) -> int:
    if total_players <= 1:
        return 1000
    percentile = (final_rank - 1) / (total_players - 1)
    seeded = round(1100 - (percentile * 200))
    return max(900, min(1100, seeded))
