from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.shop import PurchaseModel, ShopItemModel, UserInventoryModel


class ShopRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_active_items(self, guild_id: int) -> list[ShopItemModel]:
        result = await self.session.scalars(
            select(ShopItemModel)
            .where(ShopItemModel.guild_id == guild_id, ShopItemModel.active.is_(True))
            .order_by(ShopItemModel.sort_order.asc(), ShopItemModel.id.asc())
        )
        return list(result.all())

    async def get_item(self, item_id: int) -> ShopItemModel | None:
        return await self.session.get(ShopItemModel, item_id)

    async def get_item_by_sku(self, guild_id: int, sku: str) -> ShopItemModel | None:
        return await self.session.scalar(
            select(ShopItemModel).where(
                ShopItemModel.guild_id == guild_id,
                ShopItemModel.sku == sku,
            )
        )

    async def create_item(self, **kwargs) -> ShopItemModel:
        item = ShopItemModel(**kwargs)
        self.session.add(item)
        await self.session.flush()
        return item

    async def set_item_active(self, item: ShopItemModel, active: bool) -> ShopItemModel:
        item.active = active
        await self.session.flush()
        return item

    async def get_inventory_item(self, player_id: int, shop_item_id: int) -> UserInventoryModel | None:
        return await self.session.scalar(
            select(UserInventoryModel).where(
                UserInventoryModel.player_id == player_id,
                UserInventoryModel.shop_item_id == shop_item_id,
            )
        )

    async def ensure_inventory_item(self, player_id: int, shop_item_id: int) -> UserInventoryModel:
        inventory = await self.get_inventory_item(player_id, shop_item_id)
        if inventory is None:
            inventory = UserInventoryModel(player_id=player_id, shop_item_id=shop_item_id, quantity=0)
            self.session.add(inventory)
            await self.session.flush()
        return inventory

    async def create_purchase(self, **kwargs) -> PurchaseModel:
        purchase = PurchaseModel(**kwargs)
        self.session.add(purchase)
        await self.session.flush()
        return purchase
