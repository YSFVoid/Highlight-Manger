from __future__ import annotations

import discord
from discord.ext import commands

from highlight_manager.interactions.common_views import with_dismiss_button


DEFAULT_RESPONSE_TITLE = "Highlight Manager"
DEFAULT_RESPONSE_COLOUR = discord.Colour.from_rgb(68, 71, 76)


def build_response_embed(
    message: str,
    *,
    title: str = DEFAULT_RESPONSE_TITLE,
    error: bool = False,
) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=message,
        colour=discord.Colour.red() if error else DEFAULT_RESPONSE_COLOUR,
    )


async def send_context_response(
    ctx: commands.Context,
    message: str | None = None,
    *,
    embed: discord.Embed | None = None,
    error: bool = False,
    title: str = DEFAULT_RESPONSE_TITLE,
    view: discord.ui.View | None = None,
    dismissable: bool = True,
) -> discord.Message:
    final_embed = embed or build_response_embed(message or "", title=title, error=error)
    final_view = with_dismiss_button(view, getattr(ctx.author, "id", None)) if dismissable else view
    return await ctx.reply(embed=final_embed, view=final_view, mention_author=False)


async def send_interaction_response(
    interaction: discord.Interaction,
    message: str | None = None,
    *,
    embed: discord.Embed | None = None,
    error: bool = False,
    title: str = DEFAULT_RESPONSE_TITLE,
    ephemeral: bool = True,
    view: discord.ui.View | None = None,
    dismissable: bool = False,
) -> None:
    final_embed = embed or build_response_embed(message or "", title=title, error=error)
    final_view = with_dismiss_button(view, interaction.user.id) if dismissable and not ephemeral else view
    if interaction.response.is_done():
        await interaction.followup.send(embed=final_embed, ephemeral=ephemeral, view=final_view)
    else:
        await interaction.response.send_message(embed=final_embed, ephemeral=ephemeral, view=final_view)


async def edit_interaction_response(
    interaction: discord.Interaction,
    message: str | None = None,
    *,
    embed: discord.Embed | None = None,
    error: bool = False,
    title: str = DEFAULT_RESPONSE_TITLE,
    view: discord.ui.View | None = None,
) -> None:
    final_embed = embed or build_response_embed(message or "", title=title, error=error)
    await interaction.response.edit_message(content=None, embed=final_embed, view=view)
