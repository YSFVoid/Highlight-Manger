from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import ShopSection
from highlight_manager.modules.common.enums import WalletTransactionType
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.shop.repository import ShopRepository
from highlight_manager.modules.shop.service import ShopService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'shop.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_repeatable_shop_item_can_be_purchased_twice(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    profile_service = ProfileService()
    economy_service = EconomyService()
    shop_service = ShopService(economy_service)

    guilds = GuildRepository(session)
    profiles = ProfileRepository(session)
    economy = EconomyRepository(session)
    shop = ShopRepository(session)

    bundle = await guild_service.ensure_guild(guilds, 888, "Highlight")
    player = await profile_service.ensure_player(profiles, bundle.guild.id, 8801, display_name="Buyer")
    await economy_service.adjust_balance(
        economy,
        player_id=player.id,
        amount=500,
        transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
        idempotency_key="seed-wallet",
        reason="test funding",
    )
    item = await shop_service.create_item(
        shop,
        guild_id=bundle.guild.id,
        sku="repeatable-banner",
        name="Repeatable Banner",
        category="banners",
        price_coins=50,
        repeatable=True,
    )

    await shop_service.purchase_item(shop, economy, player_id=player.id, item_id=item.id, purchase_token="purchase-1")
    _, inventory, _ = await shop_service.purchase_item(
        shop,
        economy,
        player_id=player.id,
        item_id=item.id,
        purchase_token="purchase-2",
    )

    wallet = await economy.ensure_wallet(player.id)
    assert inventory.quantity == 2
    assert wallet.balance == 400


@pytest.mark.asyncio
async def test_purchase_token_is_idempotent_for_non_repeatable_item(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    profile_service = ProfileService()
    economy_service = EconomyService()
    shop_service = ShopService(economy_service)

    guilds = GuildRepository(session)
    profiles = ProfileRepository(session)
    economy = EconomyRepository(session)
    shop = ShopRepository(session)

    bundle = await guild_service.ensure_guild(guilds, 889, "Highlight")
    player = await profile_service.ensure_player(profiles, bundle.guild.id, 8901, display_name="Buyer")
    await economy_service.adjust_balance(
        economy,
        player_id=player.id,
        amount=500,
        transaction_type=WalletTransactionType.ADMIN_ADJUSTMENT,
        idempotency_key="seed-wallet-idempotent",
        reason="test funding",
    )
    item = await shop_service.create_item(
        shop,
        guild_id=bundle.guild.id,
        sku="one-time-frame",
        name="One Time Frame",
        category="frames",
        price_coins=50,
        repeatable=False,
    )

    first_purchase, first_inventory, first_transaction = await shop_service.purchase_item(
        shop,
        economy,
        player_id=player.id,
        item_id=item.id,
        purchase_token="stable-token",
    )
    second_purchase, second_inventory, second_transaction = await shop_service.purchase_item(
        shop,
        economy,
        player_id=player.id,
        item_id=item.id,
        purchase_token="stable-token",
    )

    wallet = await economy.ensure_wallet(player.id)
    assert first_purchase.id == second_purchase.id
    assert first_transaction.id == second_transaction.id
    assert first_inventory.quantity == 1
    assert second_inventory.quantity == 1
    assert wallet.balance == 450


@pytest.mark.asyncio
async def test_storefront_item_can_exist_without_coin_price(session: AsyncSession) -> None:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    guild_service = GuildService(settings)
    economy_service = EconomyService()
    shop_service = ShopService(economy_service)

    guilds = GuildRepository(session)
    shop = ShopRepository(session)

    bundle = await guild_service.ensure_guild(guilds, 890, "Highlight")
    item = await shop_service.create_item(
        shop,
        guild_id=bundle.guild.id,
        sku="dev-service",
        name="Discord Bot Source Code",
        category="development",
        price_coins=0,
        section=ShopSection.DEVELOPE,
        cash_price_text="$65 USD",
        details_text="Custom bot source delivery",
    )

    section_items = await shop_service.list_section_items(shop, bundle.guild.id, ShopSection.DEVELOPE)
    mixed_catalog = await shop_service.list_mixed_catalog(shop, bundle.guild.id)

    assert item.price_coins == 0
    assert shop_service.get_item_section(item) == ShopSection.DEVELOPE
    assert item in section_items
    assert mixed_catalog.section_configs[ShopSection.DEVELOPE].description is not None
