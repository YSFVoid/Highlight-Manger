from __future__ import annotations

import discord

from highlight_manager.ui import theme


def build_notice_embed(title: str, description: str, *, error: bool = False) -> discord.Embed:
    colour = theme.ERROR if error else theme.SURFACE
    prefix = "❌ " if error else ""
    embed = discord.Embed(
        title=f"{prefix}{title}",
        description=description,
        colour=colour,
    )
    embed.set_footer(text="Highlight Manger  •  highlight-manger.gg")
    return embed


def build_success_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{theme.EMOJI_CHECK} {title}",
        description=description,
        colour=theme.SUCCESS,
    )
    embed.set_footer(text="Highlight Manger  •  highlight-manger.gg")
    return embed


def build_reward_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"{theme.EMOJI_COIN} {title}",
        description=description,
        colour=theme.ACCENT,
    )
    embed.set_footer(text="Highlight Manger  •  Economy")
    return embed


def build_promotion_embed(player_mention: str, old_tier: str, new_tier: str) -> discord.Embed:
    """Build a celebration embed for tier promotion."""
    from highlight_manager.modules.ranks.calculator import tier_emoji
    old_emoji = tier_emoji(old_tier)
    new_emoji = tier_emoji(new_tier)
    embed = discord.Embed(
        title=f"{theme.EMOJI_SPARKLE} RANK UP {theme.EMOJI_SPARKLE}",
        description=(
            f"{player_mention} has been promoted!\n\n"
            f"{old_emoji} **{old_tier.title()}** → {new_emoji} **{new_tier.title()}**\n\n"
            f"Keep climbing the ranks! {theme.EMOJI_FIRE}"
        ),
        colour=theme.TIER_COLORS.get(new_tier, theme.ACCENT),
    )
    embed.set_footer(text="Highlight Manger  •  Competitive Ranking")
    return embed
