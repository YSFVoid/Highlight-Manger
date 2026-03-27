from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from highlight_manager.utils.embeds import build_leaderboard_embed, build_profile_embed
from highlight_manager.utils.exceptions import HighlightError

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


class GameplayCog(commands.Cog):
    def __init__(self, bot: "HighlightBot") -> None:
        self.bot = bot

    @commands.command(name="play")
    async def play(self, ctx: commands.Context, mode: str, match_type: str) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        try:
            result = await self.bot.match_service.create_match(ctx.channel, ctx.guild, ctx.author, mode, match_type)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        await ctx.reply(result.message)

    @commands.command(name="profile")
    async def profile(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        config = await self.bot.config_service.get_or_create(ctx.guild.id)
        profile = await self.bot.profile_service.ensure_member_profile(ctx.author, config)
        season = await self.bot.season_service.ensure_active(ctx.guild.id)
        await ctx.reply(embed=build_profile_embed(ctx.guild, profile, season.name))

    @commands.command(name="rank")
    async def rank(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        config = await self.bot.config_service.get_or_create(ctx.guild.id)
        profile = await self.bot.profile_service.ensure_member_profile(ctx.author, config)
        await ctx.reply(
            f"{ctx.author.mention} is currently **Rank {profile.current_rank}** with "
            f"**{profile.current_points}** points and **{profile.coins_balance}** coins."
        )

    @commands.command(name="leaderboard", aliases=["top"])
    async def leaderboard(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        profiles = await self.bot.profile_service.list_leaderboard(ctx.guild.id, limit=10)
        await ctx.reply(embed=build_leaderboard_embed(ctx.guild, profiles, title="Current Season Leaderboard"))

    @commands.command(name="stats")
    async def stats(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        target = member or ctx.author
        if not isinstance(target, discord.Member):
            return await ctx.reply("Could not find that member.")
        config = await self.bot.config_service.get_or_create(ctx.guild.id)
        profile = await self.bot.profile_service.ensure_member_profile(target, config)
        season = await self.bot.season_service.ensure_active(ctx.guild.id)
        await ctx.reply(embed=build_profile_embed(ctx.guild, profile, season.name))


async def setup(bot: "HighlightBot") -> None:
    await bot.add_cog(GameplayCog(bot))
