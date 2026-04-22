from __future__ import annotations

from datetime import date

from highlight_manager.db.models.economy import WalletTransactionModel
from highlight_manager.modules.common.exceptions import ValidationError
from highlight_manager.modules.common.enums import WalletTransactionType
from highlight_manager.modules.economy.ledger import (
    MATCH_REWARD_TYPES,
    MILESTONE_THRESHOLDS,
    daily_bonus_key,
    match_reward_key,
    milestone_key,
    tournament_reward_key,
)
from highlight_manager.modules.economy.repository import EconomyRepository


class EconomyService:
    async def adjust_balance(
        self,
        repository: EconomyRepository,
        *,
        player_id: int,
        amount: int,
        transaction_type: WalletTransactionType,
        idempotency_key: str,
        reason: str,
        related_match_id=None,
        related_purchase_id=None,
        related_tournament_id=None,
        actor_player_id: int | None = None,
    ) -> WalletTransactionModel:
        existing = await repository.get_transaction_by_key(idempotency_key)
        if existing is not None:
            return existing

        wallet = await repository.get_wallet_for_update(player_id)
        before = wallet.balance
        after = before + amount
        if after < 0:
            raise ValidationError("This action would make the wallet balance negative.")
        wallet.balance = after
        if amount > 0:
            wallet.lifetime_earned += amount
        elif amount < 0:
            wallet.lifetime_spent += abs(amount)
        return await repository.create_transaction(
            wallet_id=wallet.id,
            idempotency_key=idempotency_key,
            transaction_type=transaction_type,
            amount=amount,
            balance_before=before,
            balance_after=after,
            related_match_id=related_match_id,
            related_purchase_id=related_purchase_id,
            related_tournament_id=related_tournament_id,
            actor_player_id=actor_player_id,
            reason=reason,
        )

    def calculate_streak_bonus(self, win_streak: int) -> int:
        """Calculate bonus coins for win streaks."""
        if win_streak >= 5:
            return 5
        if win_streak >= 3:
            return 2
        return 0

    async def grant_ranked_match_rewards(
        self,
        repository: EconomyRepository,
        *,
        match_id,
        participant_ids: list[int],
        winner_ids: set[int],
        winner_mvp_id: int | None,
        loser_mvp_id: int | None,
        win_streaks: dict[int, int] | None = None,
        matches_played: dict[int, int] | None = None,
        is_first_match_today: dict[int, bool] | None = None,
    ) -> dict[int, dict[str, int]]:
        """Grant match rewards and return a per-player breakdown dict."""
        win_streaks = win_streaks or {}
        matches_played = matches_played or {}
        is_first_match_today = is_first_match_today or {}

        rewards: dict[int, dict[str, int]] = {}

        for player_id in participant_ids:
            player_rewards: dict[str, int] = {}

            # Participation reward
            await self.adjust_balance(
                repository,
                player_id=player_id,
                amount=5,
                transaction_type=MATCH_REWARD_TYPES["participation"],
                idempotency_key=match_reward_key(match_id, player_id, "participation"),
                reason="Ranked participation",
                related_match_id=match_id,
            )
            player_rewards["play"] = 5

            # Win reward
            if player_id in winner_ids:
                await self.adjust_balance(
                    repository,
                    player_id=player_id,
                    amount=5,
                    transaction_type=MATCH_REWARD_TYPES["win"],
                    idempotency_key=match_reward_key(match_id, player_id, "win"),
                    reason="Ranked win bonus",
                    related_match_id=match_id,
                )
                player_rewards["win"] = 5

            # Winner MVP reward
            if player_id == winner_mvp_id:
                await self.adjust_balance(
                    repository,
                    player_id=player_id,
                    amount=3,
                    transaction_type=MATCH_REWARD_TYPES["winner_mvp"],
                    idempotency_key=match_reward_key(match_id, player_id, "winner_mvp"),
                    reason="Winner MVP bonus",
                    related_match_id=match_id,
                )
                player_rewards["mvp"] = 3

            # Loser MVP reward
            if player_id == loser_mvp_id:
                await self.adjust_balance(
                    repository,
                    player_id=player_id,
                    amount=2,
                    transaction_type=MATCH_REWARD_TYPES["loser_mvp"],
                    idempotency_key=match_reward_key(match_id, player_id, "loser_mvp"),
                    reason="Loser MVP bonus",
                    related_match_id=match_id,
                )
                player_rewards["mvp"] = 2

            # Streak bonus (only for winners)
            streak = win_streaks.get(player_id, 0)
            if player_id in winner_ids and streak >= 3:
                streak_amount = self.calculate_streak_bonus(streak)
                await self.adjust_balance(
                    repository,
                    player_id=player_id,
                    amount=streak_amount,
                    transaction_type=MATCH_REWARD_TYPES["streak_bonus"],
                    idempotency_key=match_reward_key(match_id, player_id, "streak_bonus"),
                    reason=f"Win streak x{streak} bonus",
                    related_match_id=match_id,
                )
                player_rewards["streak"] = streak_amount

            # Daily first-match bonus
            if is_first_match_today.get(player_id, False):
                today_str = date.today().isoformat()
                await self.adjust_balance(
                    repository,
                    player_id=player_id,
                    amount=10,
                    transaction_type=MATCH_REWARD_TYPES["daily_bonus"],
                    idempotency_key=daily_bonus_key(player_id, today_str),
                    reason="First match of the day bonus",
                    related_match_id=match_id,
                )
                player_rewards["daily"] = 10

            # Milestone bonus
            total_matches = matches_played.get(player_id, 0)
            for threshold, bonus in MILESTONE_THRESHOLDS.items():
                if total_matches == threshold:
                    await self.adjust_balance(
                        repository,
                        player_id=player_id,
                        amount=bonus,
                        transaction_type=MATCH_REWARD_TYPES["milestone_bonus"],
                        idempotency_key=milestone_key(player_id, threshold),
                        reason=f"Milestone: {threshold} matches played",
                        related_match_id=match_id,
                    )
                    player_rewards["milestone"] = bonus
                    break

            rewards[player_id] = player_rewards
        return rewards

    async def grant_tournament_reward(
        self,
        repository: EconomyRepository,
        *,
        tournament_id,
        player_id: int,
        amount: int,
        transaction_type: WalletTransactionType,
        reward_kind: str,
        reason: str,
    ) -> WalletTransactionModel:
        return await self.adjust_balance(
            repository,
            player_id=player_id,
            amount=amount,
            transaction_type=transaction_type,
            idempotency_key=tournament_reward_key(tournament_id, player_id, reward_kind),
            reason=reason,
            related_tournament_id=tournament_id,
        )

