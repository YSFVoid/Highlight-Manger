from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands

from highlight_manager.models.enums import TournamentSize
from highlight_manager.utils.dates import parse_datetime_input

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


def register_tournament_commands(bot: "HighlightBot") -> None:
    async def ensure_staff(interaction: discord.Interaction) -> bool:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            if not interaction.response.is_done():
                await interaction.response.send_message("This command can only be used inside the server.", ephemeral=True)
            return False
        if not await bot.config_service.is_staff(interaction.user):
            if not interaction.response.is_done():
                await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
            return False
        return True

    tournament = app_commands.Group(name="tournament", description="Tournament management")

    @tournament.command(name="create", description="Create a tournament")
    async def tournament_create(
        interaction: discord.Interaction,
        name: str,
        size: TournamentSize,
        announcement_channel: discord.TextChannel,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        record = await bot.tournament_service.create_tournament(
            interaction.guild,
            name=name,
            size=size,
            announcement_channel=announcement_channel,
        )
        await interaction.response.send_message(
            f"Created tournament #{record.tournament_number:03d} in {announcement_channel.mention}.",
            ephemeral=True,
        )

    @tournament.command(name="start", description="Start the active tournament")
    async def tournament_start(interaction: discord.Interaction, tournament_number: int | None = None) -> None:
        if not await ensure_staff(interaction):
            return
        record = await bot.tournament_service.start_tournament(
            interaction.guild,
            (await bot.tournament_service.require_tournament(interaction.guild.id, tournament_number)).tournament_number,
        )
        await interaction.response.send_message(f"Started tournament #{record.tournament_number:03d}.", ephemeral=True)

    @tournament.command(name="close-registration", description="Close registration for the active tournament")
    async def tournament_close_registration(interaction: discord.Interaction, tournament_number: int | None = None) -> None:
        if not await ensure_staff(interaction):
            return
        target = await bot.tournament_service.require_tournament(interaction.guild.id, tournament_number)
        record = await bot.tournament_service.close_registration(interaction.guild, target.tournament_number)
        await interaction.response.send_message(
            f"Closed registration for tournament #{record.tournament_number:03d}.",
            ephemeral=True,
        )

    @tournament.command(name="set-size", description="Change tournament preset size before registrations")
    async def tournament_set_size(
        interaction: discord.Interaction,
        size: TournamentSize,
        tournament_number: int | None = None,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        target = await bot.tournament_service.require_tournament(interaction.guild.id, tournament_number)
        record = await bot.tournament_service.set_size(interaction.guild, target.tournament_number, size)
        await interaction.response.send_message(
            f"Tournament #{record.tournament_number:03d} is now set to {record.size.value}.",
            ephemeral=True,
        )

    @tournament.command(name="set-time", description="Set a schedule time for a tournament match")
    async def tournament_set_time(
        interaction: discord.Interaction,
        match_number: int,
        when: str,
        tournament_number: int | None = None,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        target = await bot.tournament_service.require_tournament(interaction.guild.id, tournament_number)
        match = await bot.tournament_service.set_match_time(
            interaction.guild,
            target.tournament_number,
            match_number,
            parse_datetime_input(when),
        )
        await interaction.response.send_message(
            f"Scheduled Match #{match.match_number:03d} for <t:{int(match.scheduled_at.timestamp())}:f>.",
            ephemeral=True,
        )

    @tournament.command(name="generate-groups", description="Generate groups and start the group stage")
    async def tournament_generate_groups(interaction: discord.Interaction, tournament_number: int | None = None) -> None:
        if not await ensure_staff(interaction):
            return
        target = await bot.tournament_service.require_tournament(interaction.guild.id, tournament_number)
        record = await bot.tournament_service.start_tournament(interaction.guild, target.tournament_number)
        await interaction.response.send_message(
            f"Generated groups and started tournament #{record.tournament_number:03d}.",
            ephemeral=True,
        )

    @tournament.command(name="advance", description="Manually advance a tournament when a stage is complete")
    async def tournament_advance(interaction: discord.Interaction, tournament_number: int | None = None) -> None:
        if not await ensure_staff(interaction):
            return
        target = await bot.tournament_service.require_tournament(interaction.guild.id, tournament_number)
        record = await bot.tournament_service.manual_advance(interaction.guild, target.tournament_number)
        await interaction.response.send_message(
            f"Processed tournament advance for #{record.tournament_number:03d}.",
            ephemeral=True,
        )

    @tournament.command(name="report-result", description="Force a tournament series result")
    async def tournament_report_result(
        interaction: discord.Interaction,
        match_number: int,
        winner_team: app_commands.Range[int, 1, 2],
        tournament_number: int | None = None,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        target = await bot.tournament_service.require_tournament(interaction.guild.id, tournament_number)
        match = await bot.tournament_service.force_result(
            interaction.guild,
            target.tournament_number,
            match_number,
            winner_team,
        )
        await interaction.response.send_message(
            f"Forced result for tournament match #{match.match_number:03d}.",
            ephemeral=True,
        )

    @tournament.command(name="cancel", description="Cancel the active tournament")
    async def tournament_cancel(
        interaction: discord.Interaction,
        reason: str,
        tournament_number: int | None = None,
    ) -> None:
        if not await ensure_staff(interaction):
            return
        target = await bot.tournament_service.require_tournament(interaction.guild.id, tournament_number)
        record = await bot.tournament_service.cancel_tournament(interaction.guild, target.tournament_number, reason=reason)
        await interaction.response.send_message(
            f"Canceled tournament #{record.tournament_number:03d}.",
            ephemeral=True,
        )

    bot.tree.add_command(tournament)
