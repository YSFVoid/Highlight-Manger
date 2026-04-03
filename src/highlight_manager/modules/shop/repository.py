from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.shop import PurchaseModel, ShopItemModel, ShopSectionConfigModel, UserInventoryModel
from highlight_manager.modules.common.enums import ShopSection


class ShopRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_items(self, guild_id: int, *, active_only: bool = True) -> list[ShopItemModel]:
        statement = (
            select(ShopItemModel)
            .where(ShopItemModel.guild_id == guild_id)
            .order_by(ShopItemModel.sort_order.asc(), ShopItemModel.id.asc())
        )
        if active_only:
            statement = statement.where(ShopItemModel.active.is_(True))
        result = await self.session.scalars(statement)
        return list(result.all())

    async def list_active_items(self, guild_id: int) -> list[ShopItemModel]:
        return await self.list_items(guild_id, active_only=True)

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

    async def update_item(self, item: ShopItemModel, **fields) -> ShopItemModel:
        for key, value in fields.items():
            setattr(item, key, value)
        await self.session.flush()
        return item

    async def set_item_active(self, item: ShopItemModel, active: bool) -> ShopItemModel:
        item.active = active
        await self.session.flush()
        return item

    async def list_section_configs(self, guild_id: int) -> list[ShopSectionConfigModel]:
        result = await self.session.scalars(
            select(ShopSectionConfigModel)
            .where(ShopSectionConfigModel.guild_id == guild_id)
            .order_by(ShopSectionConfigModel.id.asc())
        )
        return list(result.all())

    async def get_section_config(self, guild_id: int, section_key: ShopSection) -> ShopSectionConfigModel | None:
        return await self.session.scalar(
            select(ShopSectionConfigModel).where(
                ShopSectionConfigModel.guild_id == guild_id,
                ShopSectionConfigModel.section_key == section_key,
            )
        )

    async def ensure_section_config(
        self,
        guild_id: int,
        *,
        section_key: ShopSection,
        description: str | None = None,
    ) -> ShopSectionConfigModel:
        config = await self.get_section_config(guild_id, section_key)
        if config is None:
            config = ShopSectionConfigModel(
                guild_id=guild_id,
                section_key=section_key,
                description=description,
            )
            self.session.add(config)
            await self.session.flush()
        return config

    async def update_section_config(self, config: ShopSectionConfigModel, **fields) -> ShopSectionConfigModel:
        for key, value in fields.items():
            setattr(config, key, value)
        await self.session.flush()
        return config

    async def get_inventory_item(self, player_id: int, shop_item_id: int) -> UserInventoryModel | None:
        return await self.session.scalar(
            select(UserInventoryModel).where(
                UserInventoryModel.player_id == player_id,
                UserInventoryModel.shop_item_id == shop_item_id,
            )
        )

    async def get_purchase_by_wallet_transaction_id(self, wallet_transaction_id) -> PurchaseModel | None:
        return await self.session.scalar(
            select(PurchaseModel).where(PurchaseModel.wallet_transaction_id == wallet_transaction_id)
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
