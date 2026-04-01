from __future__ import annotations

import discord

from highlight_manager.ui import theme


def build_notice_embed(title: str, description: str, *, error: bool = False) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        colour=theme.ERROR if error else theme.SURFACE,
    )
    embed.set_footer(text="Highlight Manger")
    return embed
