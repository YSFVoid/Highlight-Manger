from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from highlight_manager.db.models.shop import ShopItemModel, ShopSectionConfigModel
from highlight_manager.modules.common.cache import SimpleTTLCache
from highlight_manager.modules.common.enums import ShopSection, WalletTransactionType
from highlight_manager.modules.common.exceptions import NotFoundError, ValidationError
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.shop.repository import ShopRepository


_UNSET = object()


@dataclass(slots=True)
class MixedShopCatalog:
    coin_items: list[ShopItemModel]
    storefront_items: list[ShopItemModel]
    section_configs: dict[ShopSection, ShopSectionConfigModel]


class ShopService:
    def __init__(self, economy_service: EconomyService) -> None:
        self.economy_service = economy_service
        self._catalog_cache = SimpleTTLCache(maxsize=128, ttl=120)
        self._section_cache = SimpleTTLCache(maxsize=128, ttl=120)

    async def list_catalog(self, repository: ShopRepository, guild_id: int) -> list[ShopItemModel]:
        cached = self._catalog_cache.get(str(guild_id))
        if isinstance(cached, list):
            return cached
        items = await repository.list_active_items(guild_id)
        self._catalog_cache.set(str(guild_id), items)
        return items

    async def get_cheapest_coin_item(self, repository: ShopRepository, guild_id: int) -> ShopItemModel | None:
        items = await self.list_catalog(repository, guild_id)
        coin_items = [item for item in items if item.price_coins > 0]
        if not coin_items:
            return None
        return min(coin_items, key=lambda i: i.price_coins)

    async def list_mixed_catalog(self, repository: ShopRepository, guild_id: int) -> MixedShopCatalog:
        items = await self.list_catalog(repository, guild_id)
        configs = await self.ensure_section_configs(repository, guild_id)
        coin_items = [item for item in items if item.price_coins > 0]
        storefront_items = [item for item in items if self.get_item_section(item) is not None]
        return MixedShopCatalog(
            coin_items=coin_items,
            storefront_items=storefront_items,
            section_configs=configs,
        )

    async def ensure_section_configs(
        self,
        repository: ShopRepository,
        guild_id: int,
    ) -> dict[ShopSection, ShopSectionConfigModel]:
        cached = self._section_cache.get(str(guild_id))
        if isinstance(cached, dict):
            return cached
        configs: dict[ShopSection, ShopSectionConfigModel] = {}
        for section in ShopSection:
            config = await repository.ensure_section_config(
                guild_id,
                section_key=section,
                description=self.default_section_description(section),
            )
            if not config.description:
                config = await repository.update_section_config(
                    config,
                    description=self.default_section_description(section),
                )
            configs[section] = config
        self._section_cache.set(str(guild_id), configs)
        return configs

    async def update_section_config(
        self,
        repository: ShopRepository,
        *,
        guild_id: int,
        section: ShopSection,
        channel_id: int | None | object = _UNSET,
        image_url: str | None | object = _UNSET,
        description: str | None | object = _UNSET,
        showcase_message_id: int | None | object = _UNSET,
    ) -> ShopSectionConfigModel:
        configs = await self.ensure_section_configs(repository, guild_id)
        config = configs[section]
        fields: dict[str, Any] = {}
        if channel_id is not _UNSET:
            fields["channel_id"] = channel_id
        if image_url is not _UNSET:
            fields["image_url"] = image_url
        if description is not _UNSET:
            fields["description"] = description or self.default_section_description(section)
        if showcase_message_id is not _UNSET:
            fields["showcase_message_id"] = showcase_message_id
        config = await repository.update_section_config(config, **fields)
        configs[section] = config
        self._section_cache.set(str(guild_id), configs)
        return config

    async def list_section_items(
        self,
        repository: ShopRepository,
        guild_id: int,
        section: ShopSection,
        *,
        active_only: bool = True,
    ) -> list[ShopItemModel]:
        items = await repository.list_items(guild_id, active_only=active_only)
        return [item for item in items if self.get_item_section(item) == section]

    def get_item_section(self, item: ShopItemModel) -> ShopSection | None:
        raw_value = (item.metadata_json or {}).get("section_key")
        if not raw_value:
            return None
        try:
            return ShopSection(raw_value)
        except ValueError:
            return None

    @staticmethod
    def get_item_cash_price(item: ShopItemModel) -> str | None:
        raw_value = (item.metadata_json or {}).get("cash_price_text")
        return raw_value.strip() if isinstance(raw_value, str) and raw_value.strip() else None

    @staticmethod
    def get_item_image_url(item: ShopItemModel) -> str | None:
        raw_value = (item.metadata_json or {}).get("image_url")
        return raw_value.strip() if isinstance(raw_value, str) and raw_value.strip() else None

    @staticmethod
    def get_item_details_text(item: ShopItemModel) -> str | None:
        raw_value = (item.metadata_json or {}).get("details_text")
        return raw_value.strip() if isinstance(raw_value, str) and raw_value.strip() else None

    async def create_item(
        self,
        repository: ShopRepository,
        *,
        guild_id: int,
        sku: str,
        name: str,
        category: str,
        price_coins: int | None = None,
        description: str | None = None,
        cosmetic_slot: str | None = None,
        repeatable: bool = False,
        sort_order: int = 0,
        section: ShopSection | None = None,
        image_url: str | None = None,
        cash_price_text: str | None = None,
        details_text: str | None = None,
    ) -> ShopItemModel:
        normalized_sku = sku.strip().lower()
        cleaned_name = name.strip()
        cleaned_category = category.strip()
        normalized_price = int(price_coins or 0)
        if not normalized_sku:
            raise ValidationError("SKU is required.")
        if not cleaned_name:
            raise ValidationError("Item name is required.")
        if not cleaned_category:
            raise ValidationError("Category is required.")
        if normalized_price < 0:
            raise ValidationError("Coin price cannot be negative.")
        if normalized_price == 0 and section is None:
            raise ValidationError("Set a storefront section or a coin price above zero.")
        existing = await repository.get_item_by_sku(guild_id, normalized_sku)
        if existing is not None:
            raise ValidationError("That SKU already exists.")
        metadata = self._build_item_metadata(
            section=section,
            image_url=image_url,
            cash_price_text=cash_price_text,
            details_text=details_text,
        )
        item = await repository.create_item(
            guild_id=guild_id,
            sku=normalized_sku,
            name=cleaned_name,
            description=description.strip() if description else None,
            category=cleaned_category,
            price_coins=normalized_price,
            cosmetic_slot=cosmetic_slot.strip() if cosmetic_slot else None,
            repeatable=repeatable,
            sort_order=sort_order,
            metadata_json=metadata or None,
        )
        self.invalidate_guild_cache(guild_id)
        return item

    async def update_item(
        self,
        repository: ShopRepository,
        *,
        guild_id: int,
        item_id: int,
        name: str | None = None,
        category: str | None = None,
        price_coins: int | None | object = _UNSET,
        description: str | None | object = _UNSET,
        cosmetic_slot: str | None | object = _UNSET,
        repeatable: bool | object = _UNSET,
        sort_order: int | object = _UNSET,
        section: ShopSection | None | object = _UNSET,
        image_url: str | None | object = _UNSET,
        cash_price_text: str | None | object = _UNSET,
        details_text: str | None | object = _UNSET,
    ) -> ShopItemModel:
        item = await repository.get_item(item_id)
        if item is None or item.guild_id != guild_id:
            raise NotFoundError("Shop item not found.")

        fields: dict[str, Any] = {}
        if name is not None:
            cleaned_name = name.strip()
            if not cleaned_name:
                raise ValidationError("Item name is required.")
            fields["name"] = cleaned_name
        if category is not None:
            cleaned_category = category.strip()
            if not cleaned_category:
                raise ValidationError("Category is required.")
            fields["category"] = cleaned_category
        if price_coins is not _UNSET:
            normalized_price = int(price_coins or 0)
            if normalized_price < 0:
                raise ValidationError("Coin price cannot be negative.")
            fields["price_coins"] = normalized_price
        if description is not _UNSET:
            fields["description"] = description.strip() if isinstance(description, str) and description.strip() else None
        if cosmetic_slot is not _UNSET:
            fields["cosmetic_slot"] = cosmetic_slot.strip() if isinstance(cosmetic_slot, str) and cosmetic_slot.strip() else None
        if repeatable is not _UNSET:
            fields["repeatable"] = bool(repeatable)
        if sort_order is not _UNSET:
            fields["sort_order"] = int(sort_order)

        metadata = dict(item.metadata_json or {})
        if section is not _UNSET:
            if section is None:
                metadata.pop("section_key", None)
            else:
                metadata["section_key"] = section.value
        if image_url is not _UNSET:
            self._set_metadata_value(metadata, "image_url", image_url)
        if cash_price_text is not _UNSET:
            self._set_metadata_value(metadata, "cash_price_text", cash_price_text)
        if details_text is not _UNSET:
            self._set_metadata_value(metadata, "details_text", details_text)
        final_price = fields.get("price_coins", item.price_coins)
        final_section = None
        if "section_key" in metadata:
            try:
                final_section = ShopSection(metadata["section_key"])
            except ValueError:
                final_section = None
        if final_price <= 0 and final_section is None:
            raise ValidationError("Set a storefront section or a coin price above zero.")
        fields["metadata_json"] = metadata or None
        updated = await repository.update_item(item, **fields)
        self.invalidate_guild_cache(guild_id)
        return updated

    async def set_item_active(
        self,
        repository: ShopRepository,
        *,
        guild_id: int,
        item_id: int,
        active: bool,
    ) -> ShopItemModel:
        item = await repository.get_item(item_id)
        if item is None or item.guild_id != guild_id:
            raise NotFoundError("Shop item not found.")
        updated = await repository.set_item_active(item, active)
        self.invalidate_guild_cache(guild_id)
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
        if item.price_coins <= 0:
            raise ValidationError("That item can only be ordered through the storefront.")
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

    def invalidate_guild_cache(self, guild_id: int) -> None:
        self._catalog_cache.invalidate(str(guild_id))
        self._section_cache.invalidate(str(guild_id))

    def default_section_description(self, section: ShopSection) -> str:
        descriptions = {
            ShopSection.DEVELOPE: (
                "Premium development services for serious clients.\n"
                "Discord bot source code, custom bot systems, and polished portfolio websites."
            ),
            ShopSection.OPTIMIZE_TOOL: (
                "Aggressive Windows optimization tools focused on performance.\n"
                "Built for players who want stronger tuning, cleanup, and system boost."
            ),
            ShopSection.VIDEO_EDIT: (
                "Professional video editing with multiple tiers.\n"
                "Short-form edits, 5 to 9 minute edits, and 10 to 30 minute premium edits."
            ),
            ShopSection.SENSI_PC: (
                "Free Fire PC sensitivity setup.\n"
                "Includes mouse DPI, emulator version, and X/Y sensitivity details."
            ),
            ShopSection.SENSI_IPHONE: (
                "Free Fire iPhone sensitivity setup.\n"
                "Mobile-only sensitivity values without emulator or DPI settings."
            ),
            ShopSection.SENSI_ANDROID: (
                "Free Fire Android sensitivity setup.\n"
                "Mobile-only sensitivity values without emulator or DPI settings."
            ),
        }
        return descriptions[section]

    @staticmethod
    def _build_item_metadata(
        *,
        section: ShopSection | None,
        image_url: str | None,
        cash_price_text: str | None,
        details_text: str | None,
    ) -> dict[str, str]:
        metadata: dict[str, str] = {}
        if section is not None:
            metadata["section_key"] = section.value
        if image_url and image_url.strip():
            metadata["image_url"] = image_url.strip()
        if cash_price_text and cash_price_text.strip():
            metadata["cash_price_text"] = cash_price_text.strip()
        if details_text and details_text.strip():
            metadata["details_text"] = details_text.strip()
        return metadata

    @staticmethod
    def _set_metadata_value(metadata: dict[str, Any], key: str, value: str | None | object) -> None:
        if value is _UNSET:
            return
        if isinstance(value, str) and value.strip():
            metadata[key] = value.strip()
        else:
            metadata.pop(key, None)
