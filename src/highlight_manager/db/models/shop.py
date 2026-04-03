from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import DateTime

from highlight_manager.db.base import Base
from highlight_manager.db.models._helpers import TimestampMixin, enum_column
from highlight_manager.modules.common.enums import PurchaseStatus, ShopSection
from highlight_manager.modules.common.time import utcnow


class ShopItemModel(TimestampMixin, Base):
    __tablename__ = "shop_items"
    __table_args__ = (
        UniqueConstraint("guild_id", "sku"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    price_coins: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cosmetic_slot: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    repeatable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ShopSectionConfigModel(TimestampMixin, Base):
    __tablename__ = "shop_section_configs"
    __table_args__ = (
        UniqueConstraint("guild_id", "section_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(ForeignKey("guilds.id", ondelete="CASCADE"), nullable=False)
    section_key: Mapped[ShopSection] = enum_column(ShopSection, nullable=False)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    showcase_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class UserInventoryModel(Base):
    __tablename__ = "user_inventory"
    __table_args__ = (
        UniqueConstraint("player_id", "shop_item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    shop_item_id: Mapped[int] = mapped_column(ForeignKey("shop_items.id", ondelete="CASCADE"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    equipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class PurchaseModel(Base):
    __tablename__ = "purchases"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    shop_item_id: Mapped[int] = mapped_column(ForeignKey("shop_items.id", ondelete="CASCADE"), nullable=False)
    wallet_transaction_id: Mapped[UUID] = mapped_column(
        ForeignKey("wallet_transactions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    price_coins: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[PurchaseStatus] = enum_column(PurchaseStatus, default=PurchaseStatus.COMPLETED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    actor_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"), nullable=True)
