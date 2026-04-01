from __future__ import annotations

from highlight_manager.db.models.economy import WalletTransactionModel
from highlight_manager.modules.common.exceptions import ValidationError
from highlight_manager.modules.common.enums import WalletTransactionType
from highlight_manager.modules.economy.ledger import MATCH_REWARD_TYPES, match_reward_key, tournament_reward_key
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

    async def grant_ranked_match_rewards(
        self,
        repository: EconomyRepository,
        *,
        match_id,
        participant_ids: list[int],
        winner_ids: set[int],
        winner_mvp_id: int | None,
        loser_mvp_id: int | None,
    ) -> dict[int, int]:
        deltas = {player_id: 0 for player_id in participant_ids}
        for player_id, delta in deltas.items():
            await self.adjust_balance(
                repository,
                player_id=player_id,
                amount=5,
                transaction_type=MATCH_REWARD_TYPES["participation"],
                idempotency_key=match_reward_key(match_id, player_id, "participation"),
                reason="Ranked participation",
                related_match_id=match_id,
            )
            deltas[player_id] += 5
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
                deltas[player_id] += 5
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
                deltas[player_id] += 3
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
                deltas[player_id] += 2
        return deltas

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
