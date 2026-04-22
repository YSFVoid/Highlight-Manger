from __future__ import annotations

from highlight_manager.modules.common.enums import WalletTransactionType


def match_reward_key(match_id, player_id: int, reward_kind: str) -> str:
    return f"match:{match_id}:player:{player_id}:reward:{reward_kind}"


def tournament_reward_key(tournament_id, player_id: int, reward_kind: str) -> str:
    return f"tournament:{tournament_id}:player:{player_id}:reward:{reward_kind}"


def purchase_key(player_id: int, item_id: int) -> str:
    return f"purchase:player:{player_id}:item:{item_id}"


def daily_bonus_key(player_id: int, date_str: str) -> str:
    return f"daily_bonus:player:{player_id}:date:{date_str}"


def milestone_key(player_id: int, milestone: int) -> str:
    return f"milestone:player:{player_id}:matches:{milestone}"


MATCH_REWARD_TYPES = {
    "participation": WalletTransactionType.MATCH_PARTICIPATION,
    "win": WalletTransactionType.MATCH_WIN,
    "winner_mvp": WalletTransactionType.MATCH_MVP_WINNER,
    "loser_mvp": WalletTransactionType.MATCH_MVP_LOSER,
    "streak_bonus": WalletTransactionType.STREAK_BONUS,
    "daily_bonus": WalletTransactionType.DAILY_BONUS,
    "milestone_bonus": WalletTransactionType.MILESTONE_BONUS,
}

MILESTONE_THRESHOLDS = {
    10: 20,
    25: 50,
    50: 100,
    100: 200,
}

