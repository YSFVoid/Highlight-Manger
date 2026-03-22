from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from highlight_manager.models.match import MatchRecord
from highlight_manager.services.match_service import MatchService
from highlight_manager.utils.embeds import build_leaderboard_embed, build_vote_status_embed
from highlight_manager.utils.exceptions import HighlightError

if TYPE_CHECKING:
    from highlight_manager.bot import HighlightBot


async def _safe_followup_send(
    interaction: discord.Interaction,
    *,
    content: str,
    ephemeral: bool = True,
) -> None:
    try:
        await interaction.followup.send(content, ephemeral=ephemeral)
    except (discord.NotFound, discord.Forbidden):
        return
    except discord.HTTPException as exc:
        if exc.code == 10003:
            return
        raise


class MatchQueueView(discord.ui.View):
    def __init__(
        self,
        match_service: MatchService,
        guild_id: int,
        match_number: int,
        *,
        disabled: bool = False,
        team1_full: bool = False,
        team2_full: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.match_service = match_service
        self.guild_id = guild_id
        self.match_number = match_number
        self.join_team_1.custom_id = f"match:{self.guild_id}:{self.match_number}:join1"
        self.join_team_2.custom_id = f"match:{self.guild_id}:{self.match_number}:join2"
        self.leave_match.custom_id = f"match:{self.guild_id}:{self.match_number}:leave"
        self.cancel_match.custom_id = f"match:{self.guild_id}:{self.match_number}:cancel"
        for child in self.children:
            child.disabled = disabled
        if not disabled:
            self.join_team_1.disabled = team1_full
            self.join_team_2.disabled = team2_full
            if team1_full:
                self.join_team_1.label = "Team 1 Full"
            if team2_full:
                self.join_team_2.label = "Team 2 Full"

    @discord.ui.button(label="Join Team 1", style=discord.ButtonStyle.danger, custom_id="placeholder")
    async def join_team_1(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_join(interaction, 1)

    @discord.ui.button(label="Join Team 2", style=discord.ButtonStyle.success, custom_id="placeholder")
    async def join_team_2(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._handle_join(interaction, 2)

    @discord.ui.button(label="Leave", style=discord.ButtonStyle.secondary, custom_id="placeholder")
    async def leave_match(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=False)
        try:
            result = await self.match_service.leave_open_match(interaction.user, self.match_number)
        except HighlightError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)
        await interaction.followup.send(result.message, ephemeral=True)

    @discord.ui.button(label="Cancel Game", style=discord.ButtonStyle.danger, custom_id="placeholder")
    async def cancel_match(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=False)
        try:
            match = await self.match_service.require_match(interaction.guild_id or 0, self.match_number)
            is_staff = await self.match_service.config_service.is_staff(interaction.user)
            if interaction.user.id != match.creator_id and not is_staff:
                return await interaction.followup.send(
                    "Only the creator or staff can cancel this match.",
                    ephemeral=True,
                )
            result = await self.match_service.cancel_match(
                interaction.guild,
                self.match_number,
                actor_id=interaction.user.id,
                force=is_staff,
                reason="Canceled by user action.",
            )
        except HighlightError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)
        await interaction.followup.send(result.message, ephemeral=True)

    async def _handle_join(self, interaction: discord.Interaction, team_number: int) -> None:
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=False)
        try:
            result = await self.match_service.join_team(interaction.user, self.match_number, team_number)
        except HighlightError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)
        await interaction.followup.send(result.message, ephemeral=True)


class RoomInfoEntryView(discord.ui.View):
    def __init__(
        self,
        match_service: MatchService,
        guild_id: int,
        match_number: int,
        *,
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.match_service = match_service
        self.guild_id = guild_id
        self.match_number = match_number
        self.enter_room_info.custom_id = f"roominfo:{self.guild_id}:{self.match_number}:open"
        for child in self.children:
            child.disabled = disabled

    @discord.ui.button(label="Enter Room Info", style=discord.ButtonStyle.primary, custom_id="placeholder")
    async def enter_room_info(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        try:
            match = await self.match_service.require_match(interaction.guild.id, self.match_number)
            is_staff = await self.match_service.config_service.is_staff(interaction.user)
            if interaction.user.id != match.creator_id and not is_staff:
                return await interaction.response.send_message(
                    "Only the match creator or staff can submit room info.",
                    ephemeral=True,
                )
        except HighlightError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_modal(RoomInfoModal(self.match_service, match, interaction.user))


class ResultEntryView(discord.ui.View):
    def __init__(
        self,
        match_service: MatchService,
        guild_id: int,
        match_number: int,
        *,
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.match_service = match_service
        self.guild_id = guild_id
        self.match_number = match_number
        self.submit_vote.custom_id = f"result:{self.guild_id}:{self.match_number}:submit"
        self.refresh_status.custom_id = f"result:{self.guild_id}:{self.match_number}:status"
        self.enter_room_info.custom_id = f"result:{self.guild_id}:{self.match_number}:roominfo"
        for child in self.children:
            child.disabled = disabled

    @discord.ui.button(label="Submit Vote", style=discord.ButtonStyle.success, custom_id="placeholder")
    async def submit_vote(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        try:
            match = await self.match_service.require_match(interaction.guild.id, self.match_number)
            if interaction.user.id not in match.all_player_ids:
                return await interaction.response.send_message("Only players in this match can vote.", ephemeral=True)
            view = VoteSubmissionView(self.match_service, interaction.guild, match)
        except HighlightError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_message("Submit your vote below.", view=view, ephemeral=True)

    @discord.ui.button(label="Enter Room Info", style=discord.ButtonStyle.primary, custom_id="placeholder")
    async def enter_room_info(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        room_info_view = RoomInfoEntryView(self.match_service, self.guild_id, self.match_number)
        await room_info_view.enter_room_info(interaction, _)  # type: ignore[arg-type]

    @discord.ui.button(label="Refresh Status", style=discord.ButtonStyle.secondary, custom_id="placeholder")
    async def refresh_status(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        try:
            match = await self.match_service.require_match(interaction.guild.id, self.match_number)
            votes = await self.match_service.vote_service.get_votes(match)
        except HighlightError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_message(
            embed=build_vote_status_embed(match, interaction.guild, votes),
            ephemeral=True,
        )


class CaptainWinnerSelectionView(discord.ui.View):
    def __init__(
        self,
        match_service: MatchService,
        guild_id: int,
        match_number: int,
        *,
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.match_service = match_service
        self.guild_id = guild_id
        self.match_number = match_number
        self.team_1_won.custom_id = f"captainresult:{self.guild_id}:{self.match_number}:winner:1"
        self.team_2_won.custom_id = f"captainresult:{self.guild_id}:{self.match_number}:winner:2"
        for child in self.children:
            child.disabled = disabled

    @discord.ui.button(label="Team 1 Won", style=discord.ButtonStyle.danger, custom_id="placeholder")
    async def team_1_won(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._submit(interaction, winner_team=1)

    @discord.ui.button(label="Team 2 Won", style=discord.ButtonStyle.success, custom_id="placeholder")
    async def team_2_won(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._submit(interaction, winner_team=2)

    async def _submit(self, interaction: discord.Interaction, *, winner_team: int) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=False)
        try:
            result = await self.match_service.record_captain_winner_vote(
                interaction.guild,
                self.match_number,
                interaction.user,
                winner_team=winner_team,
            )
        except HighlightError as exc:
            return await _safe_followup_send(interaction, content=str(exc), ephemeral=True)
        except Exception:
            self.match_service.logger.exception(
                "captain_winner_interaction_failed",
                guild_id=interaction.guild.id,
                match_number=self.match_number,
                actor_id=interaction.user.id,
                winner_team=winner_team,
            )
            return await _safe_followup_send(
                interaction,
                content="I hit an internal error while opening the MVP selection.",
                ephemeral=True,
            )
        await _safe_followup_send(interaction, content=result.message, ephemeral=True)


class CaptainMVPPlayerSelect(discord.ui.Select):
    def __init__(
        self,
        match_service: MatchService,
        guild_id: int,
        match_number: int,
        *,
        selection_kind: str,
        player_ids: list[int],
    ) -> None:
        self.match_service = match_service
        self.guild_id = guild_id
        self.match_number = match_number
        self.selection_kind = selection_kind
        guild = match_service.bot.get_guild(guild_id)
        options = [
            discord.SelectOption(
                label=(guild.get_member(user_id).display_name if guild and guild.get_member(user_id) else f"User {user_id}")[:100],
                value=str(user_id),
                description=f"ID: {user_id}",
            )
            for user_id in player_ids
        ]
        super().__init__(
            placeholder="Choose MVP player",
            min_values=1,
            max_values=1,
            options=options,
            custom_id=f"captainresult:{guild_id}:{match_number}:{selection_kind}:mvp",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=False)
        try:
            result = await self.match_service.record_captain_mvp_choice(
                interaction.guild,
                self.match_number,
                interaction.user,
                selection_kind=self.selection_kind,
                player_id=int(self.values[0]),
            )
        except HighlightError as exc:
            return await _safe_followup_send(interaction, content=str(exc), ephemeral=True)
        except Exception:
            self.match_service.logger.exception(
                "captain_mvp_interaction_failed",
                guild_id=interaction.guild.id,
                match_number=self.match_number,
                actor_id=interaction.user.id,
                selection_kind=self.selection_kind,
                player_id=int(self.values[0]),
            )
            return await _safe_followup_send(
                interaction,
                content="I hit an internal error while saving that MVP choice.",
                ephemeral=True,
            )
        await _safe_followup_send(interaction, content=result.message, ephemeral=True)


class CaptainMVPSelectionView(discord.ui.View):
    def __init__(
        self,
        match_service: MatchService,
        guild_id: int,
        match_number: int,
        *,
        selection_kind: str,
        player_ids: list[int],
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.add_item(
            CaptainMVPPlayerSelect(
                match_service,
                guild_id,
                match_number,
                selection_kind=selection_kind,
                player_ids=player_ids,
            )
        )
        for child in self.children:
            child.disabled = disabled


class RoomInfoModal(discord.ui.Modal, title="Enter Room Information"):
    def __init__(self, match_service: MatchService, match: MatchRecord, actor: discord.Member) -> None:
        super().__init__(timeout=300)
        self.match_service = match_service
        self.match = match
        self.actor = actor

        current_room_info = match.room_info
        self.room_id = discord.ui.TextInput(
            label="Room ID (Numbers Only)",
            placeholder="Enter the game room ID (numbers only)",
            default=current_room_info.room_id if current_room_info else None,
            max_length=24,
        )
        self.password = discord.ui.TextInput(
            label="Password (Optional)",
            placeholder="Enter room password if any",
            default=current_room_info.password if current_room_info and current_room_info.password else None,
            required=False,
            max_length=64,
        )
        self.private_match_key = discord.ui.TextInput(
            label="Private Match Key (Optional)",
            placeholder="If set, players must use this key to join",
            default=(
                current_room_info.private_match_key
                if current_room_info and current_room_info.private_match_key
                else None
            ),
            required=False,
            max_length=64,
        )
        self.add_item(self.room_id)
        self.add_item(self.password)
        self.add_item(self.private_match_key)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        actor = interaction.user if isinstance(interaction.user, discord.Member) else self.actor
        try:
            result = await self.match_service.submit_room_info(
                interaction.guild,
                self.match.match_number,
                actor,
                room_id=str(self.room_id.value),
                password=str(self.password.value) if self.password.value else None,
                private_match_key=str(self.private_match_key.value) if self.private_match_key.value else None,
            )
        except HighlightError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            self.match_service.logger.exception(
                "room_info_modal_failed",
                guild_id=interaction.guild.id if interaction.guild else None,
                match_number=self.match.match_number,
                actor_id=actor.id,
            )
            return await interaction.followup.send(
                "I hit an internal error while saving that room info.",
                ephemeral=True,
            )
        await interaction.followup.send(result.message, ephemeral=True)


class VoteSubmissionView(discord.ui.View):
    def __init__(self, match_service: MatchService, guild: discord.Guild, match: MatchRecord) -> None:
        super().__init__(timeout=300)
        self.match_service = match_service
        self.guild = guild
        self.match = match
        self.winner_team: int | None = None
        self.team1_mvp_id: int | None = None
        self.team2_mvp_id: int | None = None

        self.add_item(WinnerTeamSelect(match))
        if match.mode.team_size > 1:
            self.add_item(PlayerChoiceSelect(guild, match.team1_player_ids, "team_1_mvp", "Team 1 MVP"))
            self.add_item(PlayerChoiceSelect(guild, match.team2_player_ids, "team_2_mvp", "Team 2 MVP"))
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
    def __init__(
        self,
        guild: discord.Guild,
        user_ids: list[int],
        vote_kind: str,
        placeholder: str,
    ) -> None:
        self.vote_kind = vote_kind
        options = [
            discord.SelectOption(
                label=(guild.get_member(user_id).display_name if guild.get_member(user_id) else f"User {user_id}")[:100],
                value=str(user_id),
                description=f"ID: {user_id}",
            )
            for user_id in user_ids
        ]
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        value = int(self.values[0])
        if self.vote_kind == "team_1_mvp":
            self.view.team1_mvp_id = value
        else:
            self.view.team2_mvp_id = value
        await interaction.response.defer()


class SubmitVoteButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Confirm Vote", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: VoteSubmissionView = self.view  # type: ignore[assignment]
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("This only works inside the server.", ephemeral=True)
        if view.winner_team is None:
            return await interaction.response.send_message("Select a winner team first.", ephemeral=True)
        winner_mvp_id: int | None = None
        loser_mvp_id: int | None = None
        if view.match.mode.team_size > 1:
            if view.team1_mvp_id is None or view.team2_mvp_id is None:
                return await interaction.response.send_message(
                    "Select one MVP candidate from each team first.",
                    ephemeral=True,
                )
            if view.winner_team == 1:
                winner_mvp_id = view.team1_mvp_id
                loser_mvp_id = view.team2_mvp_id
            else:
                winner_mvp_id = view.team2_mvp_id
                loser_mvp_id = view.team1_mvp_id
        try:
            result = await view.match_service.submit_vote(
                interaction.guild,
                view.match.match_number,
                user_id=interaction.user.id,
                winner_team=view.winner_team,
                winner_mvp_id=winner_mvp_id,
                loser_mvp_id=loser_mvp_id,
            )
        except HighlightError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.edit_message(content=result.message, view=None)


class LeaderboardMetricSelect(discord.ui.Select):
    def __init__(self, current_metric: str) -> None:
        options = [
            discord.SelectOption(label="Season Points", value="points", default=current_metric == "points"),
            discord.SelectOption(label="Season Wins", value="wins", default=current_metric == "wins"),
            discord.SelectOption(label="Season MVP", value="mvp", default=current_metric == "mvp"),
        ]
        super().__init__(placeholder="Choose leaderboard view", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: LeaderboardView = self.view  # type: ignore[assignment]
        view.metric = self.values[0]
        view.page = 1
        await view.refresh(interaction)


class LeaderboardPageButton(discord.ui.Button):
    def __init__(self, *, label: str, direction: int) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.direction = direction

    async def callback(self, interaction: discord.Interaction) -> None:
        view: LeaderboardView = self.view  # type: ignore[assignment]
        view.page += self.direction
        await view.refresh(interaction)


class LeaderboardView(discord.ui.View):
    def __init__(self, bot: "HighlightBot", guild: discord.Guild, *, metric: str = "points", page_size: int = 10) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.guild = guild
        self.metric = metric
        self.page = 1
        self.page_size = page_size
        self.total_pages = 1
        self.previous_button = LeaderboardPageButton(label="Previous", direction=-1)
        self.next_button = LeaderboardPageButton(label="Next", direction=1)
        self.add_item(LeaderboardMetricSelect(self.metric))
        self.add_item(self.previous_button)
        self.add_item(self.next_button)
        self._sync_buttons()

    async def build_embed(self) -> discord.Embed:
        season = await self.bot.season_service.ensure_active(self.guild.id)
        profiles = await self.bot.profile_service.list_leaderboard_snapshot(self.guild.id, metric=self.metric)
        self.total_pages = max(1, (len(profiles) + self.page_size - 1) // self.page_size)
        self.page = min(max(self.page, 1), self.total_pages)
        start = (self.page - 1) * self.page_size
        page_profiles = profiles[start : start + self.page_size]
        self._sync_buttons()
        return build_leaderboard_embed(
            self.guild,
            page_profiles,
            title="Leaderboard",
            metric=self.metric,
            page=self.page,
            total_pages=self.total_pages,
            page_size=self.page_size,
            season_name=season.name,
        )

    async def refresh(self, interaction: discord.Interaction) -> None:
        embed = await self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    def _sync_buttons(self) -> None:
        self.previous_button.disabled = self.page <= 1
        self.next_button.disabled = self.page >= self.total_pages

