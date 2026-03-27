from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from highlight_manager.interactions.tournament_views import TournamentRegistrationView
from highlight_manager.utils.exceptions import HighlightError

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


class TournamentCog(commands.Cog):
    def __init__(self, bot: "HighlightBot") -> None:
        self.bot = bot

    @commands.group(name="tournament", invoke_without_command=True)
    async def tournament(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        try:
            tournament = await self.bot.tournament_service.require_tournament(ctx.guild.id)
            embed = await self.bot.tournament_service.get_overview_embed(ctx.guild, tournament.tournament_number)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        view = TournamentRegistrationView(
            self.bot.tournament_service,
            tournament.tournament_number,
            disabled=not tournament.registration_open,
        )
        await ctx.reply(embed=embed, view=view)

    @tournament.command(name="apply")
    async def tournament_apply(self, ctx: commands.Context) -> None:
        if not ctx.guild or not isinstance(ctx.author, discord.Member):
            return await ctx.reply("This command can only be used inside the server.")
        try:
            tournament = await self.bot.tournament_service.require_tournament(ctx.guild.id)
            embed = await self.bot.tournament_service.get_overview_embed(ctx.guild, tournament.tournament_number)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        view = TournamentRegistrationView(
            self.bot.tournament_service,
            tournament.tournament_number,
            disabled=not tournament.registration_open,
        )
        await ctx.reply(embed=embed, view=view)

    @tournament.command(name="roster")
    async def tournament_roster(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        try:
            embed = await self.bot.tournament_service.get_rosters_embed(ctx.guild)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        await ctx.reply(embed=embed)

    @tournament.command(name="bracket")
    async def tournament_bracket(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        try:
            embed = await self.bot.tournament_service.get_bracket_embed(ctx.guild)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        await ctx.reply(embed=embed)

    @tournament.command(name="standings")
    async def tournament_standings(self, ctx: commands.Context) -> None:
        if not ctx.guild:
            return await ctx.reply("This command can only be used inside the server.")
        try:
            embed = await self.bot.tournament_service.get_standings_embed(ctx.guild)
        except HighlightError as exc:
            return await ctx.reply(str(exc))
        await ctx.reply(embed=embed)


async def setup(bot: "HighlightBot") -> None:
    await bot.add_cog(TournamentCog(bot))
