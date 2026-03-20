from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from highlight_manager.config.logging import get_logger
from highlight_manager.interactions.views import LeaderboardView
from highlight_manager.utils.embeds import build_profile_embed, build_rank_embed
from highlight_manager.utils.exceptions import HighlightError

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


class GameplayCog(commands.Cog):
    def __init__(self, bot: "HighlightBot") -> None:
        self.bot = bot
        self.logger = get_logger(__name__)

    @commands.command(name="play")
    async def play(self, ctx: commands.Context, mode: str, match_type: str) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        try:
            result = await self.bot.match_service.create_match(
                ctx.channel,
                ctx.guild,
                ctx.author,
                mode,
                match_type,
                raw_command_content=ctx.message.content if ctx.message else None,
            )
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        except Exception:
            self.logger.exception(
                "play_command_handler_failed",
                guild_id=ctx.guild.id,
                user_id=ctx.author.id,
                channel_id=getattr(ctx.channel, "id", None),
                raw_command_content=ctx.message.content if ctx.message else None,
                raw_mode=mode,
                raw_type=match_type,
            )
            return await ctx.reply("I hit an internal error while processing that request.")
        await ctx.reply(result.message)

    @commands.command(name="profile")
    async def profile(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        try:
            config = await self.bot.config_service.get_or_create(ctx.guild.id)
            profile = await self.bot.profile_service.ensure_member_profile(ctx.author, config)
            season = await self.bot.season_service.ensure_active(ctx.guild.id)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        except Exception:
            self.logger.exception(
                "profile_command_failed",
                guild_id=ctx.guild.id,
                user_id=ctx.author.id,
            )
            return await ctx.reply("I hit an internal error while loading that profile.")
        await ctx.reply(embed=build_profile_embed(ctx.guild, profile, season.name))

    @commands.command(name="rank")
    async def rank(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        try:
            config = await self.bot.config_service.get_or_create(ctx.guild.id)
            profile = await self.bot.profile_service.ensure_member_profile(ctx.author, config)
            season = await self.bot.season_service.ensure_active(ctx.guild.id)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        except Exception:
            self.logger.exception(
                "rank_command_failed",
                guild_id=ctx.guild.id,
                user_id=ctx.author.id,
            )
            return await ctx.reply("I hit an internal error while loading your rank.")
        await ctx.reply(embed=build_rank_embed(ctx.guild, profile, season.name))

    @commands.command(name="leaderboard", aliases=["top"])
    async def leaderboard(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        try:
            view = LeaderboardView(self.bot, ctx.guild)
            embed = await view.build_embed()
        except Exception:
            self.logger.exception(
                "leaderboard_command_failed",
                guild_id=ctx.guild.id,
                user_id=ctx.author.id if ctx.author else None,
            )
            return await ctx.reply("I hit an internal error while loading the leaderboard.")
        await ctx.reply(embed=embed, view=view)

    @commands.command(name="stats")
    async def stats(self, ctx: commands.Context, member: discord.Member | None = None) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        target = member or ctx.author
        if not isinstance(target, discord.Member):
            return await ctx.reply("Could not find that member.")
        try:
            config = await self.bot.config_service.get_or_create(ctx.guild.id)
            profile = await self.bot.profile_service.ensure_member_profile(target, config)
            season = await self.bot.season_service.ensure_active(ctx.guild.id)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        except Exception:
            self.logger.exception(
                "stats_command_failed",
                guild_id=ctx.guild.id,
                actor_id=ctx.author.id if ctx.author else None,
                target_id=target.id,
            )
            return await ctx.reply("I hit an internal error while loading those stats.")
        await ctx.reply(embed=build_profile_embed(ctx.guild, profile, season.name))


async def setup(bot: "HighlightBot") -> None:
    await bot.add_cog(GameplayCog(bot))
