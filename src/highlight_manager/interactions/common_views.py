from __future__ import annotations

import discord


class DismissMessageButton(discord.ui.Button):
    def __init__(self, requester_id: int | None = None) -> None:
        super().__init__(label="Dismiss", style=discord.ButtonStyle.secondary)
        self.requester_id = requester_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.requester_id is not None and interaction.user.id != self.requester_id:
            embed = discord.Embed(
                title="Highlight Manager",
                description="Only the command user can dismiss this message.",
                colour=discord.Colour.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        try:
            await interaction.message.delete()  # type: ignore[union-attr]
        except discord.NotFound:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except discord.HTTPException:
            embed = discord.Embed(
                title="Highlight Manager",
                description="I could not dismiss that message right now.",
                colour=discord.Colour.red(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)


class DismissMessageView(discord.ui.View):
    def __init__(self, requester_id: int | None = None) -> None:
        super().__init__(timeout=86_400)
        self.add_item(DismissMessageButton(requester_id))


def with_dismiss_button(view: discord.ui.View | None, requester_id: int | None) -> discord.ui.View:
    if view is None:
        return DismissMessageView(requester_id)
    if any(isinstance(item, DismissMessageButton) for item in view.children):
        return view
    try:
        view.add_item(DismissMessageButton(requester_id))
    except ValueError:
        return view
    return view
