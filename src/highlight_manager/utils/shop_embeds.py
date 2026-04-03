from __future__ import annotations

import discord

from highlight_manager.models.enums import ShopSection
from highlight_manager.models.shop import ShopItem


SHOP_SECTION_COLOR = discord.Colour.from_rgb(94, 97, 102)
SHOP_ITEM_COLOR = discord.Colour.from_rgb(74, 77, 82)
SHOP_NAV_COLOR = discord.Colour.from_rgb(86, 89, 94)


def build_shop_section_embed(
    section: ShopSection,
    description: str,
    *,
    image_url: str | None,
    items: list[ShopItem],
) -> discord.Embed:
    product_lines = _section_product_lines(items)
    embed = discord.Embed(
        title=f"{section.label} | Premium Showcase",
        description=(
            f"{description}\n\n"
            f"**Products**\n{product_lines}\n\n"
            f"**How To Buy**\n{_format_bullets(_section_order_flow())}"
        ),
        colour=SHOP_SECTION_COLOR,
    )
    embed.add_field(name="Category", value=section.label, inline=True)
    embed.add_field(name="Products", value=str(len(items)), inline=True)
    embed.add_field(name="Action", value="Press Buy here", inline=True)
    embed.set_footer(text="Highlight Manager Shop | Fill the form and the bot opens a private ticket")
    if image_url:
        embed.set_image(url=image_url)
    return embed


def build_shop_item_embed(section: ShopSection, item: ShopItem) -> discord.Embed:
    pricing_lines = []
    if item.cash_price_text:
        pricing_lines.append(f"- {item.cash_price_text}")
    if item.coin_price is not None:
        pricing_lines.append(f"- {item.coin_price} coins")
    if not pricing_lines:
        pricing_lines.append("- Ask staff inside the private ticket")

    embed = discord.Embed(
        title=item.title,
        description=(
            f"**{item.title}**\n\n"
            f"**Functions**\n{_format_bullets(item.description)}\n\n"
            f"**Category**\n- {item.category_label or section.label}\n\n"
            f"**Pricing**\n{chr(10).join(pricing_lines)}\n\n"
            f"**Delivery**\n- Press Buy here\n- Fill the form\n- Bot opens a private ticket automatically"
        ),
        colour=SHOP_ITEM_COLOR,
    )
    if item.metadata_text:
        embed.add_field(name="Meta", value=item.metadata_text, inline=False)
    embed.add_field(name="Section", value=section.label, inline=True)
    embed.add_field(name="Status", value="Available", inline=True)
    next_step = "Press `Buy here` to open a private ticket"
    if item.coin_price is not None:
        next_step += f" or use `!buy {item.item_id}`"
    embed.add_field(name="Next Step", value=next_step, inline=True)
    if item.image_url:
        embed.set_image(url=item.image_url)
    embed.set_footer(text=item.metadata_text or f"Item #{item.item_id}")
    return embed


def build_shop_navigation_embed(section_lines: list[str]) -> discord.Embed:
    embed = discord.Embed(
        title="Highlight Manager Shop",
        description="Premium server products, services, and sensitivity setups.",
        colour=SHOP_NAV_COLOR,
    )
    embed.add_field(name="Sections", value="\n".join(section_lines) if section_lines else "Shop not configured yet.", inline=False)
    embed.set_footer(text="Use !shop <section> to jump directly.")
    return embed


def build_coinshop_embed(lines: list[str]) -> discord.Embed:
    embed = discord.Embed(
        title="Coin Shop",
        description="\n".join(lines) if lines else "No coin-priced items are available yet.",
        colour=SHOP_NAV_COLOR,
    )
    embed.set_footer(text="Use !buy <item_id> to buy and open a private ticket.")
    return embed


def build_shop_ticket_embed(
    *,
    buyer: discord.Member,
    section: ShopSection,
    item: ShopItem | None,
    requested_text: str,
    details: str,
    remaining_balance: str | None = None,
    ticket_number: int | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"{section.label} Shop Ticket",
        description=(
            f"{buyer.mention} selected **{item.title}**."
            if item is not None
            else f"{buyer.mention} opened a custom {section.label} shop request."
        ),
        colour=SHOP_ITEM_COLOR,
    )
    if ticket_number is not None:
        embed.add_field(name="Ticket", value=f"#{ticket_number:03d}", inline=True)
    embed.add_field(name="Section", value=section.label, inline=True)
    embed.add_field(name="Matched Item", value=item.title if item is not None else "Custom request", inline=True)
    embed.add_field(name="Buyer", value=buyer.mention, inline=True)
    embed.add_field(name="Requested Buy", value=requested_text, inline=False)
    if item is not None and item.coin_price is not None:
        embed.add_field(name="Coin Price", value=str(item.coin_price), inline=True)
    if item is not None and item.cash_price_text:
        embed.add_field(name="Cash Price", value=item.cash_price_text, inline=True)
    if remaining_balance is not None:
        embed.add_field(name="Remaining Coins", value=remaining_balance, inline=True)
    embed.add_field(name="Order Details", value=details, inline=False)
    if item is not None and item.image_url:
        embed.set_thumbnail(url=item.image_url)
    embed.set_footer(text=f"{section.label} ticket opened")
    return embed


def _section_order_flow() -> str:
    return "Press Buy here\nFill the purchase form\nThe bot opens a private ticket automatically"


def _section_product_lines(items: list[ShopItem]) -> str:
    if not items:
        return "- Ask staff for available products"
    lines: list[str] = []
    for item in items:
        price_parts: list[str] = []
        if item.cash_price_text:
            price_parts.append(item.cash_price_text)
        if item.coin_price is not None:
            price_parts.append(f"{item.coin_price} coins")
        price_text = f" - {' / '.join(price_parts)}" if price_parts else ""
        lines.append(f"- {item.title}{price_text}")
    return "\n".join(lines)


def _format_bullets(text: str) -> str:
    lines = [line.strip(" -*") for line in text.splitlines() if line.strip()]
    if not lines:
        return "- Ask staff for details"
    return "\n".join(f"- {line}" for line in lines)
