from __future__ import annotations

import discord

from highlight_manager.modules.ranks.calculator import resolve_tier, tier_emoji, tier_progress
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
    streak: int = 0,
    inventory_count: int = 0,
) -> discord.Embed:
    tier = resolve_tier(rating)
    t_emoji = tier_emoji(tier.code)
    into, total, pct = tier_progress(rating)
    tier_bar = theme.progress_bar(into, total, length=10) if total > 0 else "▓▓▓▓▓▓▓▓▓▓ MAX"
    tier_colour = theme.TIER_COLORS.get(tier.code, theme.SURFACE)

    rank_text = f"**#{leaderboard_rank}**" if leaderboard_rank is not None else "Unranked"
    streak_text = f"  {theme.EMOJI_FIRE}×{streak}" if streak >= 2 else ""

    embed = discord.Embed(
        title=f"{t_emoji} {display_name}{streak_text}",
        description=(
            f"**{tier.name}** — {season_name}\n"
            f"```{tier_bar}  {rating} pts```"
        ),
        colour=tier_colour,
    )
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(name=f"{theme.EMOJI_TROPHY} Points", value=f"**{rating}**", inline=True)
    embed.add_field(name=f"{theme.EMOJI_STAR} Peak", value=f"**{peak_rating}**", inline=True)
    embed.add_field(name="🏅 Rank", value=rank_text, inline=True)

    embed.add_field(name=f"{theme.EMOJI_SWORD} Wins", value=f"**{wins}**", inline=True)
    embed.add_field(name=f"{theme.EMOJI_SHIELD} Losses", value=f"**{losses}**", inline=True)
    embed.add_field(name="📊 Winrate", value=f"**{format_percentage(winrate)}**", inline=True)

    embed.add_field(name="🎮 Matches", value=f"**{matches_played}**", inline=True)
    embed.add_field(name=f"{theme.EMOJI_COIN} Coins", value=f"**{coins}**", inline=True)
    embed.add_field(name="🎒 Inventory", value=f"**{inventory_count}** items", inline=True)

    if total > 0:
        next_tier_name = "Next Tier"
        for i, t in enumerate(resolve_tier.__wrapped__.__code__.co_consts if hasattr(resolve_tier, '__wrapped__') else []):
            pass  # tier progress already computed above
        embed.add_field(
            name=f"{t_emoji} Tier Progress",
            value=f"`{into}/{total}` pts to next rank ({pct}%)",
            inline=False,
        )

    embed.set_footer(text=f"Highlight Manger  •  {season_name}")
    return embed


def build_leaderboard_embed(rows, players_by_id, *, season_name: str, total_players: int) -> discord.Embed:
    embed = discord.Embed(
        title=f"{theme.EMOJI_TROPHY} PLAYER LEADERBOARD",
        description=f"**{season_name}** standings — Top {len(rows)} of {total_players} players",
        colour=theme.SURFACE,
    )
    if not rows:
        embed.add_field(name="Leaderboard", value="No ranked results yet.", inline=False)
        return embed

    # Tier distribution
    tier_counts: dict[str, int] = {}
    lines = []
    for index, row in enumerate(rows, start=1):
        player = players_by_id.get(row.player_id)
        label = player.display_name if player and player.display_name else f"Player {row.player_id}"
        matches_played = row.matches_played
        winrate = (row.wins / matches_played * 100.0) if matches_played else 0.0

        tier = resolve_tier(row.rating)
        t_emoji = tier_emoji(tier.code)
        tier_counts[tier.name] = tier_counts.get(tier.name, 0) + 1

        # Medal for top 3
        position = ""
        if index == 1:
            position = "🥇"
        elif index == 2:
            position = "🥈"
        elif index == 3:
            position = "🥉"
        else:
            position = f"`#{index}`"

        lines.append(
            f"{position} {t_emoji} **{label}**\n"
            f"  Points: **{row.rating}** • W/L: **{row.wins}-{row.losses}** • WR: **{format_percentage(winrate)}**"
        )

    embed.add_field(name="Standings", value="\n\n".join(lines), inline=False)

    # Tier distribution summary
    if tier_counts:
        dist = " • ".join(f"{tier_emoji(k.lower())} {k}: **{v}**" for k, v in tier_counts.items())
        embed.add_field(name="Tier Distribution", value=dist, inline=False)

    embed.set_footer(text=f"Highlight Manger  •  {season_name}  •  Ordered by points, wins, peak")
    return embed
