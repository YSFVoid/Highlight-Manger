from __future__ import annotations

import re

import discord

from highlight_manager.utils.exceptions import HighlightError


class TournamentRegistrationView(discord.ui.View):
    def __init__(self, tournament_service, tournament_number: int, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.tournament_service = tournament_service
        self.tournament_number = tournament_number
        self.apply_button.custom_id = f"tournament:{self.tournament_number}:apply"
        for child in self.children:
            child.disabled = disabled

    @discord.ui.button(label="Apply Now", style=discord.ButtonStyle.primary, custom_id="placeholder")
    async def apply_button(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        await interaction.response.send_modal(
            TournamentApplicationModal(self.tournament_service, self.tournament_number, interaction.user),
        )


class TournamentApplicationModal(discord.ui.Modal, title="Tournament Registration"):
    team_name = discord.ui.TextInput(
        label="Team Name",
        placeholder="Enter your team name",
        max_length=80,
    )
    player_ids = discord.ui.TextInput(
        label="3 Additional Player IDs",
        placeholder="One ID per line or separated by spaces",
        style=discord.TextStyle.paragraph,
        max_length=100,
    )

    def __init__(self, tournament_service, tournament_number: int, captain: discord.Member) -> None:
        super().__init__()
        self.tournament_service = tournament_service
        self.tournament_number = tournament_number
        self.captain = captain

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        try:
            additional_ids = [int(value) for value in re.findall(r"\d+", str(self.player_ids))][:3]
            if len(additional_ids) != 3:
                return await interaction.response.send_message(
                    "Provide exactly 3 additional Discord IDs for the roster.",
                    ephemeral=True,
                )
            team = await self.tournament_service.apply_team(
                interaction.guild,
                self.tournament_number,
                self.captain,
                str(self.team_name),
                [self.captain.id, *additional_ids],
            )
        except HighlightError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_message(
            f"Registered **{team.team_name}** for tournament #{self.tournament_number:03d}.",
            ephemeral=True,
        )


class TournamentSeriesView(discord.ui.View):
    def __init__(self, tournament_service, tournament_number: int, match_number: int, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.tournament_service = tournament_service
        self.tournament_number = tournament_number
        self.match_number = match_number
        self.team1_room_win.custom_id = f"tournament-series:{tournament_number}:{match_number}:team1"
        self.team2_room_win.custom_id = f"tournament-series:{tournament_number}:{match_number}:team2"
        self.refresh.custom_id = f"tournament-series:{tournament_number}:{match_number}:refresh"
        for child in self.children:
            child.disabled = disabled

    @discord.ui.button(label="Team 1 Won Room", style=discord.ButtonStyle.success, custom_id="placeholder")
    async def team1_room_win(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_room_win(interaction, 1)

    @discord.ui.button(label="Team 2 Won Room", style=discord.ButtonStyle.success, custom_id="placeholder")
    async def team2_room_win(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_room_win(interaction, 2)

    @discord.ui.button(label="Refresh Score", style=discord.ButtonStyle.secondary, custom_id="placeholder")
    async def refresh(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        try:
            match = await self.tournament_service.require_match(
                interaction.guild.id,
                self.tournament_number,
                self.match_number,
            )
        except HighlightError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_message(
            f"Current series score: Team 1 {match.team1_room_wins} - Team 2 {match.team2_room_wins}.",
            ephemeral=True,
        )

    async def _handle_room_win(self, interaction: discord.Interaction, winning_slot: int) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        try:
            match = await self.tournament_service.report_room_win(
                interaction.guild,
                self.tournament_number,
                self.match_number,
                interaction.user,
                winning_slot,
            )
        except HighlightError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        if match.status.value == "COMPLETED":
            return await interaction.response.send_message("Series completed and bracket progression has been updated.", ephemeral=True)
        await interaction.response.send_message(
            f"Recorded room win. Team 1 {match.team1_room_wins} - Team 2 {match.team2_room_wins}.",
            ephemeral=True,
        )
