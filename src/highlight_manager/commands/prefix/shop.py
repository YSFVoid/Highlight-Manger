from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from highlight_manager.models.enums import ShopSection
from highlight_manager.utils.exceptions import HighlightError

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


class ShopCog(commands.Cog):
    def __init__(self, bot: "HighlightBot") -> None:
        self.bot = bot

    @commands.command(name="shop")
    async def shop(self, ctx: commands.Context, *, section: str | None = None) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        if section is None:
            embed = await self.bot.shop_service.build_navigation_embed(ctx.guild)
            return await ctx.reply(embed=embed)
        try:
            shop_section = ShopSection.from_input(section)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        channel = await self.bot.shop_service.get_section_channel(ctx.guild, shop_section)
        if channel is None:
            return await ctx.reply(f"**{shop_section.label}** is not configured yet. Ask staff to run `/shop setup`.")
        await ctx.reply(f"Go to {channel.mention} for **{shop_section.label}**.")


async def setup(bot: "HighlightBot") -> None:
    await bot.add_cog(ShopCog(bot))
