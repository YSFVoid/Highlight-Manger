from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from highlight_manager.db.base import Base
from highlight_manager.db.models._helpers import enum_column
from highlight_manager.modules.common.enums import WalletTransactionType
from highlight_manager.modules.common.time import utcnow


class WalletModel(Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, unique=True)
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_earned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifetime_spent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class WalletTransactionModel(Base):
    __tablename__ = "wallet_transactions"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("ix_wallet_transactions_wallet_created", "wallet_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    wallet_id: Mapped[int] = mapped_column(ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    transaction_type: Mapped[WalletTransactionType] = enum_column(
        WalletTransactionType,
        default=WalletTransactionType.ADMIN_ADJUSTMENT,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_before: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    related_match_id: Mapped[UUID | None] = mapped_column(ForeignKey("matches.id"), nullable=True)
    related_purchase_id: Mapped[UUID | None] = mapped_column(ForeignKey("purchases.id"), nullable=True)
    related_tournament_id: Mapped[UUID | None] = mapped_column(ForeignKey("tournaments.id"), nullable=True)
    actor_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
