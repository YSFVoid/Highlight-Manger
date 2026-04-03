from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.economy import WalletModel, WalletTransactionModel
from highlight_manager.modules.common.time import utcnow


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

    async def list_wallets(self) -> list[WalletModel]:
        result = await self.session.scalars(select(WalletModel).order_by(WalletModel.id.asc()))
        return list(result.all())

    async def summarize_wallet_transactions(self, wallet_id: int) -> tuple[int, int, int]:
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(WalletTransactionModel.amount), 0),
                func.coalesce(
                    func.sum(
                        case(
                            (WalletTransactionModel.amount > 0, WalletTransactionModel.amount),
                            else_=0,
                        )
                    ),
                    0,
                ),
                func.coalesce(
                    func.sum(
                        case(
                            (WalletTransactionModel.amount < 0, -WalletTransactionModel.amount),
                            else_=0,
                        )
                    ),
                    0,
                ),
            ).where(WalletTransactionModel.wallet_id == wallet_id)
        )
        balance, earned, spent = result.one()
        return int(balance or 0), int(earned or 0), int(spent or 0)

    async def update_wallet_totals(
        self,
        wallet: WalletModel,
        *,
        balance: int,
        lifetime_earned: int,
        lifetime_spent: int,
    ) -> WalletModel:
        wallet.balance = balance
        wallet.lifetime_earned = lifetime_earned
        wallet.lifetime_spent = lifetime_spent
        wallet.updated_at = utcnow()
        await self.session.flush()
        return wallet

    async def create_transaction(self, **kwargs) -> WalletTransactionModel:
        transaction = WalletTransactionModel(**kwargs)
        self.session.add(transaction)
        await self.session.flush()
        return transaction
