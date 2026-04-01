from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.economy import WalletModel, WalletTransactionModel


class EconomyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_wallet(self, player_id: int) -> WalletModel:
        wallet = await self.session.scalar(select(WalletModel).where(WalletModel.player_id == player_id))
        if wallet is None:
            wallet = WalletModel(player_id=player_id)
            self.session.add(wallet)
            await self.session.flush()
        return wallet

    async def get_wallet_for_update(self, player_id: int) -> WalletModel:
        wallet = await self.session.scalar(
            select(WalletModel).where(WalletModel.player_id == player_id).with_for_update()
        )
        if wallet is None:
            wallet = WalletModel(player_id=player_id)
            self.session.add(wallet)
            await self.session.flush()
        return wallet

    async def get_transaction_by_key(self, idempotency_key: str) -> WalletTransactionModel | None:
        return await self.session.scalar(
            select(WalletTransactionModel).where(WalletTransactionModel.idempotency_key == idempotency_key)
        )

    async def create_transaction(self, **kwargs) -> WalletTransactionModel:
        transaction = WalletTransactionModel(**kwargs)
        self.session.add(transaction)
        await self.session.flush()
        return transaction
