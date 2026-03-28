from __future__ import annotations

import discord

from highlight_manager.models.match import MatchRecord
from highlight_manager.services.match_service import MatchService
from highlight_manager.utils.embeds import build_vote_status_embed
from highlight_manager.utils.exceptions import HighlightError
from highlight_manager.utils.response_helpers import edit_interaction_response, send_interaction_response


class MatchQueueView(discord.ui.View):
    def __init__(self, match_service: MatchService, match_number: int, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.match_service = match_service
        self.match_number = match_number
        self.join_team_1.custom_id = f"match:{self.match_number}:join1"
        self.join_team_2.custom_id = f"match:{self.match_number}:join2"
        self.leave_match.custom_id = f"match:{self.match_number}:leave"
        self.cancel_match.custom_id = f"match:{self.match_number}:cancel"
        for child in self.children:
            child.disabled = disabled

    @discord.ui.button(label="Join Team 1", style=discord.ButtonStyle.success, custom_id="placeholder")
    async def join_team_1(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_join(interaction, 1)

    @discord.ui.button(label="Join Team 2", style=discord.ButtonStyle.success, custom_id="placeholder")
    async def join_team_2(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_join(interaction, 2)

    @discord.ui.button(label="Leave Match", style=discord.ButtonStyle.secondary, custom_id="placeholder")
    async def leave_match(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await send_interaction_response(interaction, "This only works inside the server.", error=True, ephemeral=True)
        try:
            result = await self.match_service.leave_open_match(interaction.user, self.match_number)
        except HighlightError as exc:
            return await send_interaction_response(interaction, str(exc), error=True, ephemeral=True)
        await send_interaction_response(interaction, result.message, ephemeral=True)

    @discord.ui.button(label="Cancel Match", style=discord.ButtonStyle.danger, custom_id="placeholder")
    async def cancel_match(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await send_interaction_response(interaction, "This only works inside the server.", error=True, ephemeral=True)
        try:
            match = await self.match_service.require_match(interaction.guild_id or 0, self.match_number)
            is_staff = await self.match_service.config_service.is_staff(interaction.user)
            if interaction.user.id != match.creator_id and not is_staff:
                return await send_interaction_response(interaction, "Only the creator or staff can cancel this match.", error=True, ephemeral=True)
            result = await self.match_service.cancel_match(
                interaction.guild,
                self.match_number,
                actor_id=interaction.user.id,
                force=is_staff,
                reason="Canceled by user action.",
            )
        except HighlightError as exc:
            return await send_interaction_response(interaction, str(exc), error=True, ephemeral=True)
        await send_interaction_response(interaction, result.message, ephemeral=True)

    async def _handle_join(self, interaction: discord.Interaction, team_number: int) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await send_interaction_response(interaction, "This only works inside the server.", error=True, ephemeral=True)
        try:
            result = await self.match_service.join_team(interaction.user, self.match_number, team_number)
        except HighlightError as exc:
            return await send_interaction_response(interaction, str(exc), error=True, ephemeral=True)
        await send_interaction_response(interaction, result.message, ephemeral=True)

class ResultEntryView(discord.ui.View):
    def __init__(self, match_service: MatchService, match_number: int, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.match_service = match_service
        self.match_number = match_number
        self.submit_vote.custom_id = f"result:{self.match_number}:submit"
        self.refresh_status.custom_id = f"result:{self.match_number}:status"
        self.cancel_match.custom_id = f"result:{self.match_number}:cancel"
        for child in self.children:
            child.disabled = disabled

    @discord.ui.button(label="Submit Vote", style=discord.ButtonStyle.primary, custom_id="placeholder")
    async def submit_vote(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await send_interaction_response(interaction, "This only works inside the server.", error=True, ephemeral=True)
        try:
            match = await self.match_service.require_match(interaction.guild.id, self.match_number)
            if interaction.user.id not in match.all_player_ids:
                return await send_interaction_response(interaction, "Only players in this match can vote.", error=True, ephemeral=True)
            view = VoteSubmissionView(self.match_service, interaction.guild, match)
        except HighlightError as exc:
            return await send_interaction_response(interaction, str(exc), error=True, ephemeral=True)
        await send_interaction_response(interaction, "Submit your vote below.", view=view, ephemeral=True)

    @discord.ui.button(label="Refresh Status", style=discord.ButtonStyle.secondary, custom_id="placeholder")
    async def refresh_status(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            return await send_interaction_response(interaction, "This only works inside the server.", error=True, ephemeral=True)
        try:
            match = await self.match_service.require_match(interaction.guild.id, self.match_number)
            votes = await self.match_service.vote_service.get_votes(match)
        except HighlightError as exc:
            return await send_interaction_response(interaction, str(exc), error=True, ephemeral=True)
        await send_interaction_response(interaction, embed=build_vote_status_embed(match, interaction.guild, votes), ephemeral=True)

    @discord.ui.button(label="Cancel Match", style=discord.ButtonStyle.danger, custom_id="placeholder")
    async def cancel_match(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await send_interaction_response(interaction, "This only works inside the server.", error=True, ephemeral=True)
        try:
            result = await self.match_service.cancel_result_room_match(
                interaction.guild,
                self.match_number,
                interaction.user,
            )
        except HighlightError as exc:
            return await send_interaction_response(interaction, str(exc), error=True, ephemeral=True)
        await send_interaction_response(interaction, result.message, ephemeral=True)

class VoteSubmissionView(discord.ui.View):
    def __init__(self, match_service: MatchService, guild: discord.Guild, match: MatchRecord) -> None:
        super().__init__(timeout=300)
        self.match_service = match_service
        self.guild = guild
        self.match = match
        self.winner_team: int | None = None
        self.winner_mvp_id: int | None = None
        self.loser_mvp_id: int | None = None

        self.add_item(WinnerTeamSelect(match))
        if match.mode.team_size > 1:
            self.add_item(PlayerChoiceSelect(guild, match, "winner_mvp"))
            self.add_item(PlayerChoiceSelect(guild, match, "loser_mvp"))
        self.add_item(SubmitVoteButton())


class WinnerTeamSelect(discord.ui.Select):
    def __init__(self, match: MatchRecord) -> None:
        super().__init__(
            placeholder="Select winner team",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Team 1", value="1"),
                discord.SelectOption(label="Team 2", value="2"),
            ],
        )
        self.match = match

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.winner_team = int(self.values[0])
        await interaction.response.defer()


class PlayerChoiceSelect(discord.ui.Select):
    def __init__(self, guild: discord.Guild, match: MatchRecord, vote_kind: str) -> None:
        self.vote_kind = vote_kind
        options = [
            discord.SelectOption(
                label=(guild.get_member(user_id).display_name if guild.get_member(user_id) else f"User {user_id}")[:100],
                value=str(user_id),
                description=f"ID: {user_id}",
            )
            for user_id in match.all_player_ids
        ]
        placeholder = "Select winner MVP" if vote_kind == "winner_mvp" else "Select loser MVP"
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        value = int(self.values[0])
        if self.vote_kind == "winner_mvp":
            self.view.winner_mvp_id = value
        else:
            self.view.loser_mvp_id = value
        await interaction.response.defer()


class SubmitVoteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Confirm Vote", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: VoteSubmissionView = self.view  # type: ignore[assignment]
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await send_interaction_response(interaction, "This only works inside the server.", error=True, ephemeral=True)
        if view.winner_team is None:
            return await send_interaction_response(interaction, "Select a winner team first.", error=True, ephemeral=True)
        try:
            result = await view.match_service.submit_vote(
                interaction.guild,
                view.match.match_number,
                user_id=interaction.user.id,
                winner_team=view.winner_team,
                winner_mvp_id=view.winner_mvp_id,
                loser_mvp_id=view.loser_mvp_id,
            )
        except HighlightError as exc:
            return await send_interaction_response(interaction, str(exc), error=True, ephemeral=True)
        await edit_interaction_response(interaction, result.message, view=None)
