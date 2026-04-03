from __future__ import annotations

from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from highlight_manager.modules.common.cache import SimpleTTLCache
from highlight_manager.modules.common.enums import WalletTransactionType
from highlight_manager.modules.common.exceptions import NotFoundError, ValidationError
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.shop.repository import ShopRepository


class ShopService:
    def __init__(self, economy_service: EconomyService) -> None:
        self.economy_service = economy_service
        self._catalog_cache = SimpleTTLCache(maxsize=128, ttl=120)

    async def list_catalog(self, repository: ShopRepository, guild_id: int):
        cached = self._catalog_cache.get(str(guild_id))
        if isinstance(cached, list):
            return cached
        items = await repository.list_active_items(guild_id)
        self._catalog_cache.set(str(guild_id), items)
        return items

    async def create_item(
        self,
        repository: ShopRepository,
        *,
        guild_id: int,
        sku: str,
        name: str,
        category: str,
        price_coins: int,
        description: str | None = None,
        cosmetic_slot: str | None = None,
        repeatable: bool = False,
        sort_order: int = 0,
    ):
        normalized_sku = sku.strip().lower()
        cleaned_name = name.strip()
        cleaned_category = category.strip()
        if not normalized_sku:
            raise ValidationError("SKU is required.")
        if not cleaned_name:
            raise ValidationError("Item name is required.")
        if not cleaned_category:
            raise ValidationError("Category is required.")
        if price_coins <= 0:
            raise ValidationError("Price must be greater than zero.")
        existing = await repository.get_item_by_sku(guild_id, normalized_sku)
        if existing is not None:
            raise ValidationError("That SKU already exists.")
        item = await repository.create_item(
            guild_id=guild_id,
            sku=normalized_sku,
            name=cleaned_name,
            description=description.strip() if description else None,
            category=cleaned_category,
            price_coins=price_coins,
            cosmetic_slot=cosmetic_slot.strip() if cosmetic_slot else None,
            repeatable=repeatable,
            sort_order=sort_order,
        )
        self._catalog_cache.invalidate(str(guild_id))
        return item

    async def set_item_active(
        self,
        repository: ShopRepository,
        *,
        guild_id: int,
        item_id: int,
        active: bool,
    ):
        item = await repository.get_item(item_id)
        if item is None or item.guild_id != guild_id:
            raise NotFoundError("Shop item not found.")
        updated = await repository.set_item_active(item, active)
        self._catalog_cache.invalidate(str(guild_id))
        return updated

    async def purchase_item(
        self,
        repository: ShopRepository,
        economy_repository: EconomyRepository,
        *,
        player_id: int,
        item_id: int,
        purchase_token: str | None = None,
    ):
        item = await repository.get_item(item_id)
        if item is None or not item.active:
            raise ValidationError("That shop item is not available.")
        if purchase_token:
            existing_transaction = await economy_repository.get_transaction_by_key(purchase_token)
            if existing_transaction is not None:
                existing_purchase = await repository.get_purchase_by_wallet_transaction_id(existing_transaction.id)
                if existing_purchase is not None:
                    inventory = await repository.get_inventory_item(player_id, item.id)
                    if inventory is None:
                        raise ValidationError("Purchase history exists but inventory is missing for that item.")
                    return existing_purchase, inventory, existing_transaction
        existing_inventory = await repository.get_inventory_item(player_id, item.id)
        if existing_inventory is not None and not item.repeatable:
            raise ValidationError("You already own that cosmetic.")

        transaction = await self.economy_service.adjust_balance(
            economy_repository,
            player_id=player_id,
            amount=-item.price_coins,
            transaction_type=WalletTransactionType.PURCHASE,
            idempotency_key=purchase_token or f"purchase:player:{player_id}:item:{item.id}:{uuid4()}",
            reason=f"Purchased {item.name}",
        )
        existing_purchase = await repository.get_purchase_by_wallet_transaction_id(transaction.id)
        if existing_purchase is not None:
            inventory = await repository.get_inventory_item(player_id, item.id)
            if inventory is None:
                raise ValidationError("Purchase history exists but inventory is missing for that item.")
            return existing_purchase, inventory, transaction
        inventory = await repository.get_inventory_item(player_id, item.id)
        if inventory is not None and not item.repeatable:
            raise ValidationError("You already own that cosmetic.")
        try:
            inventory = await repository.ensure_inventory_item(player_id, item.id)
            inventory.quantity += 1
            purchase = await repository.create_purchase(
                player_id=player_id,
                shop_item_id=item.id,
                wallet_transaction_id=transaction.id,
                price_coins=item.price_coins,
            )
        except IntegrityError as exc:
            raise ValidationError("That purchase was already processed or is no longer valid.") from exc
        return purchase, inventory, transaction
