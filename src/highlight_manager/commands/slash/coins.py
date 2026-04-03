from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from highlight_manager.models.enums import AuditAction
from highlight_manager.utils.response_helpers import send_interaction_response

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


def register_coins_commands(bot: "HighlightBot") -> None:
    async def ensure_staff(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            if not interaction.response.is_done():
                await send_interaction_response(interaction, "This command can only be used inside the server.", error=True, ephemeral=True)
            return False
        if not await bot.config_service.is_staff(interaction.user):
            if not interaction.response.is_done():
                await send_interaction_response(interaction, "You do not have permission to use this command.", error=True, ephemeral=True)
            return False
        return True

    coins = app_commands.Group(name="coins", description="Coins economy management")

    @coins.command(name="add", description="Add coins to a member")
    async def coins_add(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]) -> None:
        if not await ensure_staff(interaction):
            return
        result = await bot.coins_service.adjust_balance(interaction.guild, member.id, amount)
        await bot.audit_service.log(
            interaction.guild,
            AuditAction.COINS_UPDATED,
            f"Added {amount} coins to {member.mention}.",
            actor_id=interaction.user.id,
            target_id=member.id,
        )
        await send_interaction_response(
            interaction,
            f"{member.mention}: {result.previous_balance} -> {result.new_balance} coins.",
            ephemeral=True,
        )

    @coins.command(name="remove", description="Remove coins from a member")
    async def coins_remove(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 1, 1_000_000]) -> None:
        if not await ensure_staff(interaction):
            return
        result = await bot.coins_service.adjust_balance(interaction.guild, member.id, -amount)
        await bot.audit_service.log(
            interaction.guild,
            AuditAction.COINS_UPDATED,
            f"Removed {amount} coins from {member.mention}.",
            actor_id=interaction.user.id,
            target_id=member.id,
        )
        await send_interaction_response(
            interaction,
            f"{member.mention}: {result.previous_balance} -> {result.new_balance} coins.",
            ephemeral=True,
        )

    @coins.command(name="set", description="Set a member's coin balance")
    async def coins_set(interaction: discord.Interaction, member: discord.Member, amount: app_commands.Range[int, 0, 1_000_000]) -> None:
        if not await ensure_staff(interaction):
            return
        result = await bot.coins_service.set_balance(interaction.guild, member.id, amount)
        await bot.audit_service.log(
            interaction.guild,
            AuditAction.COINS_UPDATED,
            f"Set {member.mention} to {amount} coins.",
            actor_id=interaction.user.id,
            target_id=member.id,
        )
        await send_interaction_response(
            interaction,
            f"{member.mention}: {result.previous_balance} -> {result.new_balance} coins.",
            ephemeral=True,
        )

    bot.tree.add_command(coins)
