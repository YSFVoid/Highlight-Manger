from __future__ import annotations

import discord


def build_tournament_embed(tournament, teams, matches) -> discord.Embed:
    embed = discord.Embed(
        title=f"Tournament • {tournament.name}",
        description=f"State: **{tournament.state.value.replace('_', ' ').title()}**",
        colour=discord.Colour.from_rgb(45, 62, 170),
    )
    embed.add_field(name="Teams", value=str(len(teams)), inline=True)
    embed.add_field(name="Matches", value=str(len(matches)), inline=True)
    embed.add_field(name="Format", value=tournament.format.value.replace("_", " ").title(), inline=True)
    return embed
