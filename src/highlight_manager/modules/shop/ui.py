from __future__ import annotations

import discord

from highlight_manager.db.models.shop import ShopItemModel, ShopSectionConfigModel
from highlight_manager.modules.common.enums import ShopSection
from highlight_manager.modules.shop.service import ShopService


STOREFRONT_FOOTER_PREFIX = "Highlight Manger Storefront"


def build_shop_embed(
    *,
    coin_items: list[ShopItemModel],
    section_configs: dict[ShopSection, ShopSectionConfigModel],
) -> discord.Embed:
    embed = discord.Embed(
        title="Highlight Manger Shop",
        description="Coins, premium services, and storefront sections in one place.",
        colour=discord.Colour.from_rgb(46, 61, 160),
    )
    if coin_items:
        catalog_lines = [
            f"`#{item.id}` **{item.name}** • {item.price_coins} coins"
            for item in coin_items[:8]
        ]
        embed.add_field(name="Coin Catalog", value="\n".join(catalog_lines), inline=False)
    else:
        embed.add_field(name="Coin Catalog", value="No coin-priced items are active right now.", inline=False)

    section_lines: list[str] = []
    for section in ShopSection:
        config = section_configs.get(section)
        if config is None or config.channel_id is None:
            section_lines.append(f"**{section.label}** → Not configured")
        else:
            section_lines.append(f"**{section.label}** → <#{config.channel_id}>")
    embed.add_field(
        name="Storefront Sections",
        value="\n".join(section_lines),
        inline=False,
    )
    embed.set_footer(text="Use the posted storefront channels for Buy Now requests.")
    return embed


def build_storefront_section_embed(
    *,
    section: ShopSection,
    config: ShopSectionConfigModel,
    items: list[ShopItemModel],
    shop_service: ShopService,
) -> discord.Embed:
    description = config.description or shop_service.default_section_description(section)
    product_lines = _build_section_product_lines(items, shop_service)
    embed = discord.Embed(
        title=f"{section.label} | Premium Showcase",
        description=(
            f"{description}\n\n"
            f"**Products**\n{product_lines}\n\n"
            "**How To Buy**\n"
            "- Press Buy Now\n"
            "- Fill the request form\n"
            "- The bot opens a private ticket automatically"
        ),
        colour=discord.Colour.from_rgb(86, 89, 94),
    )
    embed.add_field(name="Category", value=section.label, inline=True)
    embed.add_field(name="Products", value=str(len(items)), inline=True)
    embed.add_field(name="Action", value="Press Buy Now", inline=True)
    if config.image_url:
        embed.set_image(url=config.image_url)
    embed.set_footer(text=f"{STOREFRONT_FOOTER_PREFIX} | {section.value}")
    return embed


def build_storefront_ticket_embed(
    *,
    buyer_mention: str,
    section: ShopSection,
    requested_text: str,
    details_text: str,
    matched_item: ShopItemModel | None,
    shop_service: ShopService,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{section.label} Order Ticket",
        description=(
            f"{buyer_mention} opened a {section.label} storefront request."
            if matched_item is None
            else f"{buyer_mention} requested **{matched_item.name}** from {section.label}."
        ),
        colour=discord.Colour.from_rgb(74, 77, 82),
    )
    embed.add_field(name="Buyer", value=buyer_mention, inline=True)
    embed.add_field(name="Section", value=section.label, inline=True)
    embed.add_field(name="Matched Item", value=matched_item.name if matched_item else "Custom request", inline=True)
    embed.add_field(name="Requested Product", value=requested_text, inline=False)
    if matched_item and matched_item.price_coins > 0:
        embed.add_field(name="Coin Price", value=str(matched_item.price_coins), inline=True)
    cash_price_text = shop_service.get_item_cash_price(matched_item) if matched_item else None
    if cash_price_text:
        embed.add_field(name="Cash Price", value=cash_price_text, inline=True)
    details_value = details_text.strip() if details_text.strip() else "No extra details were provided."
    embed.add_field(name="Order Details", value=details_value, inline=False)
    image_url = shop_service.get_item_image_url(matched_item) if matched_item else None
    if image_url:
        embed.set_thumbnail(url=image_url)
    embed.set_footer(text=f"{section.label} storefront request")
    return embed


def _build_section_product_lines(items: list[ShopItemModel], shop_service: ShopService) -> str:
    if not items:
        return "- No active products are published in this section yet."
    lines: list[str] = []
    for item in items:
        price_parts: list[str] = []
        cash_price_text = shop_service.get_item_cash_price(item)
        if cash_price_text:
            price_parts.append(cash_price_text)
        if item.price_coins > 0:
            price_parts.append(f"{item.price_coins} coins")
        price_suffix = f" - {' / '.join(price_parts)}" if price_parts else ""
        lines.append(f"- **{item.name}**{price_suffix}")
    return "\n".join(lines)
