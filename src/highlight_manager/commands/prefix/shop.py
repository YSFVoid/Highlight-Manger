from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from highlight_manager.models.enums import ShopSection
from highlight_manager.utils.exceptions import HighlightError
from highlight_manager.utils.response_helpers import send_context_response

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


class ShopCog(commands.Cog):
    def __init__(self, bot: "HighlightBot") -> None:
        self.bot = bot

    @commands.command(name="shop")
    async def shop(self, ctx: commands.Context, *, section: str | None = None) -> None:
        if not ctx.guild:
            return await send_context_response(ctx, "This command can only be used inside the server.", error=True)
        if section is None:
            embed = await self.bot.shop_service.build_navigation_embed(ctx.guild)
            return await send_context_response(ctx, embed=embed)
        try:
            shop_section = ShopSection.from_input(section)
        except HighlightError as exc:
            return await send_context_response(ctx, str(exc), error=True)
        channel = await self.bot.shop_service.get_section_channel(ctx.guild, shop_section)
        if channel is None:
            return await send_context_response(ctx, f"**{shop_section.label}** is not configured yet. Ask staff to run `/shop setup`.", error=True)
        await send_context_response(ctx, f"Go to {channel.mention} for **{shop_section.label}**.")


async def setup(bot: "HighlightBot") -> None:
    await bot.add_cog(ShopCog(bot))
