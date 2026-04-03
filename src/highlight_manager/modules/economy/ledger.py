from __future__ import annotations

from highlight_manager.modules.common.enums import WalletTransactionType


def match_reward_key(match_id, player_id: int, reward_kind: str) -> str:
    return f"match:{match_id}:player:{player_id}:reward:{reward_kind}"


def tournament_reward_key(tournament_id, player_id: int, reward_kind: str) -> str:
    return f"tournament:{tournament_id}:player:{player_id}:reward:{reward_kind}"


def purchase_key(player_id: int, item_id: int) -> str:
    return f"purchase:player:{player_id}:item:{item_id}"


MATCH_REWARD_TYPES = {
    "participation": WalletTransactionType.MATCH_PARTICIPATION,
    "win": WalletTransactionType.MATCH_WIN,
    "winner_mvp": WalletTransactionType.MATCH_MVP_WINNER,
    "loser_mvp": WalletTransactionType.MATCH_MVP_LOSER,
}
