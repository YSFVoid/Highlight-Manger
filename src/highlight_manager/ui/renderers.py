from __future__ import annotations

import discord

from highlight_manager.ui import theme


def format_percentage(value: float) -> str:
    if value.is_integer():
        return f"{int(value)}%"
    return f"{value:.1f}%"


def build_profile_embed(
    *,
    display_name: str,
    rating: int,
    wins: int,
    losses: int,
    coins: int,
    matches_played: int,
    winrate: float,
    leaderboard_rank: int | None,
    peak_rating: int,
    season_name: str,
    avatar_url: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=display_name,
        description=f"{season_name} competitive profile",
        colour=theme.SURFACE,
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
    embed.add_field(name="Points", value=f"**{rating}**", inline=True)
    embed.add_field(name="Wins", value=f"**{wins}**", inline=True)
    embed.add_field(name="Losses", value=f"**{losses}**", inline=True)
    embed.add_field(name="Matches", value=f"**{matches_played}**", inline=True)
    embed.add_field(name="Winrate", value=f"**{format_percentage(winrate)}**", inline=True)
    embed.add_field(name="Peak", value=f"**{peak_rating}**", inline=True)
    embed.add_field(name="Coins", value=f"**{coins}**", inline=True)
    embed.add_field(
        name="Leaderboard Rank",
        value=f"**#{leaderboard_rank}**" if leaderboard_rank is not None else "**Unranked**",
        inline=True,
    )
    embed.add_field(name="Season", value=f"**{season_name}**", inline=True)
    embed.set_footer(text="Winrate is based on confirmed ranked matches.")
    return embed


def build_leaderboard_embed(rows, players_by_id, *, season_name: str, total_players: int) -> discord.Embed:
    embed = discord.Embed(
        title="PLAYER LEADERBOARD",
        description=f"{season_name} standings | Top {len(rows)} of {total_players} players",
        colour=theme.SURFACE,
    )
    if not rows:
        embed.add_field(name="Leaderboard", value="No ranked results yet.", inline=False)
        return embed
    lines = []
    for index, row in enumerate(rows, start=1):
        player = players_by_id.get(row.player_id)
        label = player.display_name if player and player.display_name else f"Player {row.player_id}"
        matches_played = row.matches_played
        winrate = (row.wins / matches_played * 100.0) if matches_played else 0.0
        lines.append(
            f"**#{index}** {label}\n"
            f"Points: **{row.rating}** | W-L: **{row.wins}-{row.losses}** | Winrate: **{format_percentage(winrate)}**"
        )
    embed.add_field(name="Standings", value="\n\n".join(lines), inline=False)
    embed.set_footer(text="Leaderboard order: points, wins, peak, matches played.")
    return embed
