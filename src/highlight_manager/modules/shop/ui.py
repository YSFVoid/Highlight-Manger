from __future__ import annotations

import discord

from highlight_manager.db.models.shop import ShopItemModel, ShopSectionConfigModel
from highlight_manager.modules.common.enums import ShopSection
from highlight_manager.modules.shop.service import ShopService
from highlight_manager.ui import theme


STOREFRONT_FOOTER_PREFIX = "Highlight Manger Storefront"

_SECTION_EMOJI = {
    ShopSection.DEVELOPE: "💻",
    ShopSection.OPTIMIZE_TOOL: "⚙️",
    ShopSection.VIDEO_EDIT: "🎬",
    ShopSection.SENSI_PC: "🖥️",
    ShopSection.SENSI_IPHONE: "📱",
    ShopSection.SENSI_ANDROID: "📱",
}


def build_shop_embed(
    *,
    coin_items: list[ShopItemModel],
    section_configs: dict[ShopSection, ShopSectionConfigModel],
    player_coins: int = 0,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{theme.EMOJI_COIN} Highlight Manger Shop",
        description=(
            f"**Your Balance:** `{player_coins}` coins {theme.EMOJI_COIN}\n\n"
            f"{theme.EMOJI_SWORD} **Win matches** → {theme.EMOJI_COIN} **Earn coins** → 🛒 **Buy rewards**\n"
            "─────────────────────────"
        ),
        colour=theme.ACCENT,
    )
    if coin_items:
        catalog_lines = []
        for item in coin_items[:10]:
            affordable = "✅" if player_coins >= item.price_coins else "🔒"
            catalog_lines.append(
                f"{affordable} `#{item.id}` **{item.name}** — `{item.price_coins}` coins"
            )
        embed.add_field(
            name=f"🛍️ Coin Catalog ({len(coin_items)} items)",
            value="\n".join(catalog_lines),
            inline=False,
        )
    else:
        embed.add_field(
            name="🛍️ Coin Catalog",
            value="No coin-priced items are active right now.",
            inline=False,
        )

    section_lines: list[str] = []
    for section in ShopSection:
        emoji = _SECTION_EMOJI.get(section, "📦")
        config = section_configs.get(section)
        if config is None or config.channel_id is None:
            section_lines.append(f"{emoji} **{section.label}** → `Not configured`")
        else:
            section_lines.append(f"{emoji} **{section.label}** → <#{config.channel_id}>")
    embed.add_field(
        name=f"{theme.EMOJI_SPARKLE} Storefront Sections",
        value="\n".join(section_lines),
        inline=False,
    )
    embed.set_footer(text="Highlight Manger  •  Shop  •  Use storefronts for Buy Now requests")
    return embed


def build_storefront_section_embed(
    *,
    section: ShopSection,
    config: ShopSectionConfigModel,
    items: list[ShopItemModel],
    shop_service: ShopService,
) -> discord.Embed:
    emoji = _SECTION_EMOJI.get(section, "📦")
    description = config.description or shop_service.default_section_description(section)
    product_lines = _build_section_product_lines(items, shop_service)
    embed = discord.Embed(
        title=f"{emoji} {section.label} | Premium Showcase",
        description=(
            f"{description}\n\n"
            f"**Products**\n{product_lines}\n\n"
            "**How To Buy**\n"
            f"1️⃣ Press **Buy Now** {theme.EMOJI_COIN}\n"
            "2️⃣ Fill the request form\n"
            f"3️⃣ Bot opens a private ticket automatically {theme.EMOJI_SPARKLE}"
        ),
        colour=theme.ACCENT,
    )
    embed.add_field(name=f"{emoji} Category", value=section.label, inline=True)
    embed.add_field(name="📦 Products", value=str(len(items)), inline=True)
    embed.add_field(name="🛒 Action", value="Press **Buy Now**", inline=True)
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
    emoji = _SECTION_EMOJI.get(section, "📦")
    embed = discord.Embed(
        title=f"🎫 {section.label} Order Ticket",
        description=(
            f"{buyer_mention} opened a {section.label} storefront request."
            if matched_item is None
            else f"{buyer_mention} requested **{matched_item.name}** from {section.label}."
        ),
        colour=theme.ACCENT,
    )
    embed.add_field(name="👤 Buyer", value=buyer_mention, inline=True)
    embed.add_field(name=f"{emoji} Section", value=section.label, inline=True)
    embed.add_field(name="📦 Item", value=matched_item.name if matched_item else "Custom request", inline=True)
    embed.add_field(name="📝 Requested Product", value=requested_text, inline=False)
    if matched_item and matched_item.price_coins > 0:
        embed.add_field(name=f"{theme.EMOJI_COIN} Coin Price", value=f"`{matched_item.price_coins}` coins", inline=True)
    cash_price_text = shop_service.get_item_cash_price(matched_item) if matched_item else None
    if cash_price_text:
        embed.add_field(name="💵 Cash Price", value=cash_price_text, inline=True)
    details_value = details_text.strip() if details_text.strip() else "No extra details were provided."
    embed.add_field(name="📋 Order Details", value=details_value, inline=False)
    image_url = shop_service.get_item_image_url(matched_item) if matched_item else None
    if image_url:
        embed.set_thumbnail(url=image_url)
    embed.set_footer(text=f"Highlight Manger  •  {section.label} storefront request")
    return embed


def _build_section_product_lines(items: list[ShopItemModel], shop_service: ShopService) -> str:
    if not items:
        return "No active products are published in this section yet."
    lines: list[str] = []
    for item in items:
        price_parts: list[str] = []
        cash_price_text = shop_service.get_item_cash_price(item)
        if cash_price_text:
            price_parts.append(f"💵 {cash_price_text}")
        if item.price_coins > 0:
            price_parts.append(f"{theme.EMOJI_COIN} {item.price_coins} coins")
        price_suffix = f" — {' / '.join(price_parts)}" if price_parts else ""
        lines.append(f"• **{item.name}**{price_suffix}")
    return "\n".join(lines)
