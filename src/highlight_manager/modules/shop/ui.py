from __future__ import annotations

import discord


def build_shop_embed(items) -> discord.Embed:
    embed = discord.Embed(
        title="Highlight Manger Shop",
        description="Cosmetic-first rewards powered by coins.",
        colour=discord.Colour.from_rgb(46, 61, 160),
    )
    if not items:
        embed.add_field(name="Catalog", value="No items are active right now.", inline=False)
        return embed
    for item in items[:10]:
        embed.add_field(
            name=f"#{item.id} - {item.name} - {item.price_coins} coins",
            value=f"`{item.sku}` | {item.description or item.category}",
            inline=False,
        )
    return embed
