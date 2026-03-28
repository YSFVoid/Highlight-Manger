from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import discord

from highlight_manager.models.enums import (
    AuditAction,
    TournamentMatchStatus,
    TournamentPhase,
    TournamentSize,
    TournamentTeamStatus,
)
from highlight_manager.models.tournament import TournamentMatchRecord, TournamentRecord, TournamentTeam
from highlight_manager.repositories.tournament_repository import (
    TournamentMatchRepository,
    TournamentRepository,
    TournamentTeamRepository,
)
from highlight_manager.services.audit_service import AuditService
from highlight_manager.services.coins_service import CoinsService
from highlight_manager.services.config_service import ConfigService
from highlight_manager.services.tournament_bracket_service import TournamentBracketService
from highlight_manager.services.tournament_standings_service import TournamentStandingsService
from highlight_manager.services.voice_service import VoiceService
from highlight_manager.utils.dates import utcnow
from highlight_manager.utils.exceptions import UserFacingError
from highlight_manager.utils.response_helpers import build_response_embed
from highlight_manager.utils.tournament_embeds import (
    build_champion_embed,
    build_group_standings_embed,
    build_tournament_bracket_embed,
    build_tournament_embed,
    build_tournament_match_embed,
    build_tournament_roster_embed,
)


class TournamentService:
    REMINDER_MINUTES = 15

    def __init__(
        self,
        bot: discord.Client,
        tournament_repository: TournamentRepository,
        team_repository: TournamentTeamRepository,
        match_repository: TournamentMatchRepository,
        config_service: ConfigService,
        coins_service: CoinsService,
        audit_service: AuditService,
        voice_service: VoiceService,
    ) -> None:
        self.bot = bot
        self.tournament_repository = tournament_repository
        self.team_repository = team_repository
        self.match_repository = match_repository
        self.config_service = config_service
        self.coins_service = coins_service
        self.audit_service = audit_service
        self.voice_service = voice_service
        self.bracket_service = TournamentBracketService()
        self.standings_service = TournamentStandingsService()

    async def create_tournament(
        self,
        guild: discord.Guild,
        *,
        name: str,
        size: TournamentSize,
        announcement_channel: discord.TextChannel,
    ) -> TournamentRecord:
        active = await self.tournament_repository.get_active(guild.id)
        if active is not None:
            raise UserFacingError("There is already an active tournament in this server.")
        latest = await self.tournament_repository.get_latest(guild.id)
        number = (latest.tournament_number + 1) if latest else 1
        preset = self.bracket_service.get_preset(size)
        tournament = TournamentRecord(
            guild_id=guild.id,
            tournament_number=number,
            name=name,
            size=size,
            max_teams=preset["max_teams"],
            group_count=preset["group_count"],
            advancing_per_group=preset["advancing_per_group"],
            announcement_channel_id=announcement_channel.id,
        )
        tournament = await self.tournament_repository.create(tournament)
        tournament = await self.refresh_announcement(guild, tournament)
        await self.audit_service.log(
            guild,
            AuditAction.TOURNAMENT_CREATED,
            f"Created tournament #{tournament.tournament_number:03d} ({tournament.name}).",
            metadata={"size": size.value},
        )
        return tournament

    async def cancel_tournament(self, guild: discord.Guild, tournament_number: int, *, reason: str) -> TournamentRecord:
        tournament = await self.require_tournament(guild.id, tournament_number)
        tournament.phase = TournamentPhase.CANCELED
        tournament.registration_open = False
        tournament.canceled_at = utcnow()
        tournament = await self.tournament_repository.replace(tournament)
        await self.refresh_announcement(guild, tournament)
        await self.audit_service.log(
            guild,
            AuditAction.TOURNAMENT_UPDATED,
            f"Canceled tournament #{tournament.tournament_number:03d}. Reason: {reason}",
            metadata={"reason": reason},
        )
        return tournament

    async def set_size(
        self,
        guild: discord.Guild,
        tournament_number: int,
        size: TournamentSize,
    ) -> TournamentRecord:
        tournament = await self.require_tournament(guild.id, tournament_number)
        if tournament.phase != TournamentPhase.REGISTRATION:
            raise UserFacingError("Tournament size can only be changed during registration.")
        teams = await self.team_repository.list_for_tournament(guild.id, tournament_number)
        if teams:
            raise UserFacingError("Tournament size cannot be changed after teams have registered.")
        preset = self.bracket_service.get_preset(size)
        tournament.size = size
        tournament.max_teams = preset["max_teams"]
        tournament.group_count = preset["group_count"]
        tournament.advancing_per_group = preset["advancing_per_group"]
        tournament = await self.tournament_repository.replace(tournament)
        return await self.refresh_announcement(guild, tournament)

    async def get_active_tournament(self, guild_id: int) -> TournamentRecord | None:
        return await self.tournament_repository.get_active(guild_id)

    async def get_overview_embed(self, guild: discord.Guild, tournament_number: int | None = None) -> discord.Embed:
        tournament = await self.require_tournament(guild.id, tournament_number)
        teams = await self.team_repository.list_for_tournament(guild.id, tournament.tournament_number)
        return build_tournament_embed(tournament, len(teams))

    async def require_tournament(self, guild_id: int, tournament_number: int | None = None) -> TournamentRecord:
        tournament = (
            await self.tournament_repository.get_active(guild_id)
            if tournament_number is None
            else await self.tournament_repository.get(guild_id, tournament_number)
        )
        if tournament is None:
            raise UserFacingError("Tournament not found.")
        return tournament

    async def apply_team(
        self,
        guild: discord.Guild,
        tournament_number: int,
        captain: discord.Member,
        team_name: str,
        player_ids: list[int],
    ) -> TournamentTeam:
        tournament = await self.require_tournament(guild.id, tournament_number)
        if tournament.phase != TournamentPhase.REGISTRATION or not tournament.registration_open:
            raise UserFacingError("Tournament registration is closed.")
        if len(player_ids) != tournament.team_size:
            raise UserFacingError(f"Teams must have exactly {tournament.team_size} players.")
        if len(set(player_ids)) != len(player_ids):
            raise UserFacingError("Duplicate players are not allowed in one roster.")
        if player_ids[0] != captain.id:
            raise UserFacingError("The captain must be the first player in the roster.")
        for user_id in player_ids:
            member = guild.get_member(user_id)
            if member is None or member.bot:
                raise UserFacingError(f"Player ID `{user_id}` is not a valid guild member.")
            existing = await self.team_repository.find_by_player(guild.id, tournament.tournament_number, user_id)
            if existing is not None:
                raise UserFacingError(f"<@{user_id}> is already registered on team **{existing.team_name}**.")
        teams = await self.team_repository.list_for_tournament(guild.id, tournament.tournament_number)
        if len(teams) >= tournament.max_teams:
            raise UserFacingError("Tournament registration is already full.")
        latest_team = await self.team_repository.get_latest_team(guild.id, tournament.tournament_number)
        team_number = (latest_team.team_number + 1) if latest_team else 1
        team = TournamentTeam(
            guild_id=guild.id,
            tournament_number=tournament.tournament_number,
            team_number=team_number,
            team_name=team_name,
            captain_id=captain.id,
            player_ids=player_ids,
        )
        team = await self.team_repository.create(team)
        updated_teams = teams + [team]
        if len(updated_teams) >= tournament.max_teams:
            tournament.registration_open = False
            tournament = await self.tournament_repository.replace(tournament)
            await self.start_tournament(guild, tournament.tournament_number)
            return team
        await self.refresh_announcement(guild, tournament)
        await self.audit_service.log(
            guild,
            AuditAction.TOURNAMENT_UPDATED,
            f"Team **{team.team_name}** joined tournament #{tournament.tournament_number:03d}.",
            actor_id=captain.id,
            metadata={"team_number": team.team_number},
        )
        return team

    async def close_registration(self, guild: discord.Guild, tournament_number: int) -> TournamentRecord:
        tournament = await self.require_tournament(guild.id, tournament_number)
        if tournament.phase != TournamentPhase.REGISTRATION:
            raise UserFacingError("That tournament is no longer in registration.")
        tournament.registration_open = False
        tournament = await self.tournament_repository.replace(tournament)
        await self.refresh_announcement(guild, tournament)
        return tournament

    async def start_tournament(self, guild: discord.Guild, tournament_number: int) -> TournamentRecord:
        tournament = await self.require_tournament(guild.id, tournament_number)
        if tournament.phase != TournamentPhase.REGISTRATION:
            raise UserFacingError("This tournament has already started.")
        teams = await self.team_repository.list_for_tournament(guild.id, tournament_number)
        if len(teams) != tournament.max_teams:
            raise UserFacingError("Tournament cannot start until all team slots are filled.")
        groups = self.bracket_service.assign_groups(teams, tournament.group_count)
        for group_label, group_teams in groups.items():
            for team in group_teams:
                team.group_label = group_label
                await self.team_repository.replace(team)
        for group_label, team1_id, team2_id, round_label in self.bracket_service.build_group_pairings(groups):
            tournament = await self._create_match_record(
                tournament,
                phase=TournamentPhase.GROUP_STAGE,
                round_label=round_label,
                group_label=group_label,
                team1_id=team1_id,
                team2_id=team2_id,
            )
        tournament.phase = TournamentPhase.GROUP_STAGE
        tournament.registration_open = False
        tournament.started_at = utcnow()
        tournament = await self.tournament_repository.replace(tournament)
        tournament = await self.refresh_announcement(guild, tournament)
        await self.audit_service.log(
            guild,
            AuditAction.TOURNAMENT_STARTED,
            f"Tournament #{tournament.tournament_number:03d} started.",
        )
        return tournament

    async def set_match_time(
        self,
        guild: discord.Guild,
        tournament_number: int,
        match_number: int,
        scheduled_at,
    ) -> TournamentMatchRecord:
        tournament = await self.require_tournament(guild.id, tournament_number)
        match = await self.require_match(guild.id, tournament_number, match_number)
        match.scheduled_at = scheduled_at
        if match.status == TournamentMatchStatus.SCHEDULED:
            match.status = TournamentMatchStatus.READY
        match = await self.match_repository.replace(match)
        await self.ensure_match_voices(guild, tournament, match)
        await self.ensure_result_room(guild, tournament, match)
        return match

    async def report_room_win(
        self,
        guild: discord.Guild,
        tournament_number: int,
        match_number: int,
        reporter: discord.Member,
        winning_slot: int,
    ) -> TournamentMatchRecord:
        tournament = await self.require_tournament(guild.id, tournament_number)
        match = await self.require_match(guild.id, tournament_number, match_number)
        team1 = await self.team_repository.get(guild.id, tournament_number, match.team1_id)
        team2 = await self.team_repository.get(guild.id, tournament_number, match.team2_id)
        if team1 is None or team2 is None:
            raise UserFacingError("Match teams could not be resolved.")
        is_staff = await self.config_service.is_staff(reporter)
        if reporter.id not in {team1.captain_id, team2.captain_id} and not is_staff:
            raise UserFacingError("Only captains or staff can report tournament room wins.")
        if match.status in {TournamentMatchStatus.COMPLETED, TournamentMatchStatus.CANCELED}:
            raise UserFacingError("That tournament match is already closed.")
        if winning_slot == 1:
            match.team1_room_wins += 1
        elif winning_slot == 2:
            match.team2_room_wins += 1
        else:
            raise UserFacingError("Winning slot must be Team 1 or Team 2.")
        match.status = TournamentMatchStatus.IN_PROGRESS
        if match.team1_room_wins >= 2 or match.team2_room_wins >= 2:
            return await self.complete_match(guild, tournament, match)
        match = await self.match_repository.replace(match)
        await self.refresh_result_room(guild, tournament, match)
        return match

    async def force_result(
        self,
        guild: discord.Guild,
        tournament_number: int,
        match_number: int,
        winner_slot: int,
    ) -> TournamentMatchRecord:
        tournament = await self.require_tournament(guild.id, tournament_number)
        match = await self.require_match(guild.id, tournament_number, match_number)
        if match.status in {TournamentMatchStatus.COMPLETED, TournamentMatchStatus.CANCELED}:
            raise UserFacingError("That tournament match is already closed.")
        if winner_slot == 1:
            match.team1_room_wins = max(match.team1_room_wins, 2)
        elif winner_slot == 2:
            match.team2_room_wins = max(match.team2_room_wins, 2)
        else:
            raise UserFacingError("Winner slot must be Team 1 or Team 2.")
        return await self.complete_match(guild, tournament, match)

    async def complete_match(
        self,
        guild: discord.Guild,
        tournament: TournamentRecord,
        match: TournamentMatchRecord,
    ) -> TournamentMatchRecord:
        if match.status == TournamentMatchStatus.COMPLETED and match.winner_team_id is not None:
            return match
        team1 = await self.team_repository.get(guild.id, tournament.tournament_number, match.team1_id)
        team2 = await self.team_repository.get(guild.id, tournament.tournament_number, match.team2_id)
        if team1 is None or team2 is None:
            raise UserFacingError("Could not resolve tournament teams for completion.")
        match.winner_team_id = match.team1_id if match.team1_room_wins > match.team2_room_wins else match.team2_id
        loser_team = team2 if match.winner_team_id == team1.team_number else team1
        winner_team = team1 if match.winner_team_id == team1.team_number else team2
        match.status = TournamentMatchStatus.COMPLETED
        match.completed_at = utcnow()
        match = await self.match_repository.replace(match)
        await self.voice_service.cleanup_tournament_voices(guild, match)
        match.team1_voice_channel_id = None
        match.team2_voice_channel_id = None
        match = await self.match_repository.replace(match)

        updated_team1 = await self.coins_service.award_tournament_participation(guild, team1)
        updated_team2 = await self.coins_service.award_tournament_participation(guild, team2)
        if updated_team1.participation_rewarded != team1.participation_rewarded:
            await self.team_repository.replace(updated_team1)
        if updated_team2.participation_rewarded != team2.participation_rewarded:
            await self.team_repository.replace(updated_team2)

        await self.refresh_result_room(guild, tournament, match)
        await self.audit_service.log(
            guild,
            AuditAction.TOURNAMENT_RESULT_REPORTED,
            f"Tournament Match #{match.match_number:03d} completed. Winner: **{winner_team.team_name}**.",
            metadata={"tournament_number": tournament.tournament_number},
        )

        if match.phase == TournamentPhase.GROUP_STAGE:
            group_matches = await self.match_repository.list_for_phase(guild.id, tournament.tournament_number, TournamentPhase.GROUP_STAGE)
            if group_matches and all(item.status == TournamentMatchStatus.COMPLETED for item in group_matches):
                tournament = await self._generate_knockout_stage(guild, tournament)
        elif match.phase == TournamentPhase.KNOCKOUT:
            tournament = await self._advance_knockout_if_ready(guild, tournament, match.round_label)

        if tournament.phase == TournamentPhase.COMPLETED:
            await self.coins_service.award_tournament_final_rewards(
                guild,
                champion_team=winner_team if tournament.champion_team_id == winner_team.team_number else loser_team,
                runner_up_team=loser_team if tournament.runner_up_team_id == loser_team.team_number else winner_team,
            )
        return match

    async def get_rosters_embed(self, guild: discord.Guild, tournament_number: int | None = None) -> discord.Embed:
        tournament = await self.require_tournament(guild.id, tournament_number)
        teams = await self.team_repository.list_for_tournament(guild.id, tournament.tournament_number)
        return build_tournament_roster_embed(tournament, teams)

    async def get_bracket_embed(self, guild: discord.Guild, tournament_number: int | None = None) -> discord.Embed:
        tournament = await self.require_tournament(guild.id, tournament_number)
        teams = await self.team_repository.list_for_tournament(guild.id, tournament.tournament_number)
        teams_by_id = {team.team_number: team for team in teams}
        matches = await self.match_repository.list_for_tournament(guild.id, tournament.tournament_number)
        return build_tournament_bracket_embed(tournament, matches, teams_by_id)

    async def get_standings_embed(self, guild: discord.Guild, tournament_number: int | None = None) -> discord.Embed:
        tournament = await self.require_tournament(guild.id, tournament_number)
        teams = await self.team_repository.list_for_tournament(guild.id, tournament.tournament_number)
        matches = await self.match_repository.list_for_phase(guild.id, tournament.tournament_number, TournamentPhase.GROUP_STAGE)
        standings = self.standings_service.compute_group_standings(teams, matches)
        teams_by_id = {team.team_number: team for team in teams}
        return build_group_standings_embed(tournament, standings, teams_by_id)

    async def refresh_announcement(self, guild: discord.Guild, tournament: TournamentRecord) -> TournamentRecord:
        channel = guild.get_channel(tournament.announcement_channel_id) if tournament.announcement_channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return tournament
        teams = await self.team_repository.list_for_tournament(guild.id, tournament.tournament_number)
        embed = build_tournament_embed(tournament, len(teams))
        view = self._build_registration_view(
            tournament,
            disabled=tournament.phase != TournamentPhase.REGISTRATION or not tournament.registration_open,
        )
        if tournament.announcement_message_id:
            try:
                message = await channel.fetch_message(tournament.announcement_message_id)
                await message.edit(embed=embed, view=view)
            except discord.NotFound:
                message = await channel.send(embed=embed, view=view)
                tournament.announcement_message_id = message.id
        else:
            message = await channel.send(embed=embed, view=view)
            tournament.announcement_message_id = message.id
        tournament.registration_message_id = tournament.announcement_message_id
        return await self.tournament_repository.replace(tournament)

    async def ensure_result_room(
        self,
        guild: discord.Guild,
        tournament: TournamentRecord,
        match: TournamentMatchRecord,
    ) -> TournamentMatchRecord:
        if match.result_channel_id and match.result_message_id:
            return match
        config = await self.config_service.get_or_create(guild.id)
        category = guild.get_channel(config.result_category_id) if config.result_category_id else None
        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                manage_channels=True,
            )
        for role_id in {*(config.admin_role_ids or []), *(config.staff_role_ids or [])}:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        team1 = await self.team_repository.get(guild.id, tournament.tournament_number, match.team1_id)
        team2 = await self.team_repository.get(guild.id, tournament.tournament_number, match.team2_id)
        for user_id in set((team1.player_ids if team1 else []) + (team2.player_ids if team2 else [])):
            member = guild.get_member(user_id)
            if member:
                overwrites[member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        channel = await guild.create_text_channel(
            name=f"tournament-{tournament.tournament_number:03d}-{match.match_number:03d}",
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            reason=f"Tournament Match #{match.match_number:03d} result room",
        )
        message = await channel.send(
            embed=build_tournament_match_embed(tournament, match, team1, team2),
            view=self._build_series_view(tournament.tournament_number, match.match_number),
        )
        match.result_channel_id = channel.id
        match.result_message_id = message.id
        match = await self.match_repository.replace(match)
        return match

    async def ensure_match_voices(
        self,
        guild: discord.Guild,
        tournament: TournamentRecord,
        match: TournamentMatchRecord,
    ) -> TournamentMatchRecord:
        if match.team1_voice_channel_id and match.team2_voice_channel_id:
            return match
        config = await self.config_service.get_or_create(guild.id)
        team1_channel, team2_channel = await self.voice_service.create_tournament_voice_channels(
            guild,
            tournament,
            match,
            config,
        )
        match.team1_voice_channel_id = team1_channel.id
        match.team2_voice_channel_id = team2_channel.id
        return await self.match_repository.replace(match)

    async def refresh_result_room(
        self,
        guild: discord.Guild,
        tournament: TournamentRecord,
        match: TournamentMatchRecord,
    ) -> None:
        if not match.result_channel_id:
            return
        channel = guild.get_channel(match.result_channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        team1 = await self.team_repository.get(guild.id, tournament.tournament_number, match.team1_id)
        team2 = await self.team_repository.get(guild.id, tournament.tournament_number, match.team2_id)
        view = self._build_series_view(
            tournament.tournament_number,
            match.match_number,
            disabled=match.status == TournamentMatchStatus.COMPLETED,
        )
        if match.result_message_id:
            try:
                message = await channel.fetch_message(match.result_message_id)
                await message.edit(embed=build_tournament_match_embed(tournament, match, team1, team2), view=view)
                return
            except discord.NotFound:
                pass
        message = await channel.send(embed=build_tournament_match_embed(tournament, match, team1, team2), view=view)
        match.result_message_id = message.id
        await self.match_repository.replace(match)

    async def process_due_events(self) -> None:
        now = utcnow()
        reminder_cutoff = now + timedelta(minutes=self.REMINDER_MINUTES)
        for match in await self.match_repository.list_due_reminders(now, reminder_cutoff):
            guild = self.bot.get_guild(match.guild_id)
            if guild is None:
                continue
            tournament = await self.tournament_repository.get(match.guild_id, match.tournament_number)
            if tournament is None:
                continue
            team1 = await self.team_repository.get(guild.id, tournament.tournament_number, match.team1_id)
            team2 = await self.team_repository.get(guild.id, tournament.tournament_number, match.team2_id)
            channel = guild.get_channel(tournament.announcement_channel_id) if tournament.announcement_channel_id else None
            if isinstance(channel, discord.TextChannel):
                await channel.send(
                    embed=build_response_embed(
                        f"Upcoming tournament series in {self.REMINDER_MINUTES}m: "
                        f"**{team1.team_name if team1 else match.team1_id}** vs **{team2.team_name if team2 else match.team2_id}** "
                        f"for Match #{match.match_number:03d}."
                    )
                )
            match.reminder_sent_at = now
            match = await self.match_repository.replace(match)
            await self.ensure_match_voices(guild, tournament, match)
            await self.ensure_result_room(guild, tournament, match)

    async def manual_advance(self, guild: discord.Guild, tournament_number: int) -> TournamentRecord:
        tournament = await self.require_tournament(guild.id, tournament_number)
        if tournament.phase == TournamentPhase.GROUP_STAGE:
            group_matches = await self.match_repository.list_for_phase(guild.id, tournament_number, TournamentPhase.GROUP_STAGE)
            if not group_matches or any(match.status != TournamentMatchStatus.COMPLETED for match in group_matches):
                raise UserFacingError("Group stage is not fully completed yet.")
            return await self._generate_knockout_stage(guild, tournament)
        if tournament.phase == TournamentPhase.KNOCKOUT:
            knockout_matches = await self.match_repository.list_for_phase(guild.id, tournament_number, TournamentPhase.KNOCKOUT)
            if not knockout_matches:
                raise UserFacingError("No knockout matches exist yet.")
            latest_round = knockout_matches[-1].round_label
            return await self._advance_knockout_if_ready(guild, tournament, latest_round)
        raise UserFacingError("Manual advance is only available for active tournaments.")

    async def reconcile_active_tournaments(self) -> None:
        for guild in self.bot.guilds:
            active = await self.tournament_repository.get_active(guild.id)
            if active is None:
                continue
            self.register_views(active)
            for match in await self.match_repository.list_open_result_rooms(guild.id):
                self.bot.add_view(self._build_series_view(match.tournament_number, match.match_number))

    def register_views(self, tournament: TournamentRecord) -> None:
        self.bot.add_view(
            self._build_registration_view(
                tournament,
                disabled=tournament.phase != TournamentPhase.REGISTRATION or not tournament.registration_open,
            ),
        )

    async def require_match(self, guild_id: int, tournament_number: int, match_number: int) -> TournamentMatchRecord:
        match = await self.match_repository.get(guild_id, tournament_number, match_number)
        if match is None:
            raise UserFacingError(f"Tournament match #{match_number:03d} was not found.")
        return match

    async def _create_match_record(
        self,
        tournament: TournamentRecord,
        *,
        phase: TournamentPhase,
        round_label: str,
        team1_id: int,
        team2_id: int,
        group_label: str | None = None,
    ) -> TournamentRecord:
        match = TournamentMatchRecord(
            guild_id=tournament.guild_id,
            tournament_number=tournament.tournament_number,
            match_number=tournament.next_match_number,
            phase=phase,
            round_label=round_label,
            group_label=group_label,
            team1_id=team1_id,
            team2_id=team2_id,
        )
        await self.match_repository.create(match)
        tournament.next_match_number += 1
        return await self.tournament_repository.replace(tournament)

    async def _generate_knockout_stage(self, guild: discord.Guild, tournament: TournamentRecord) -> TournamentRecord:
        teams = await self.team_repository.list_for_tournament(guild.id, tournament.tournament_number)
        group_matches = await self.match_repository.list_for_phase(guild.id, tournament.tournament_number, TournamentPhase.GROUP_STAGE)
        standings = self.standings_service.compute_group_standings(teams, group_matches)
        qualified: dict[str, list[TournamentTeam]] = defaultdict(list)
        teams_by_id = {team.team_number: team for team in teams}
        for group_label, rows in standings.items():
            for row in rows[: tournament.advancing_per_group]:
                qualified[group_label].append(teams_by_id[row["team_id"]])
        round_label, pairs = self.bracket_service.seed_knockout(tournament.size, qualified)
        for team1_id, team2_id in pairs:
            tournament = await self._create_match_record(
                tournament,
                phase=TournamentPhase.KNOCKOUT,
                round_label=round_label,
                team1_id=team1_id,
                team2_id=team2_id,
            )
        tournament.phase = TournamentPhase.KNOCKOUT
        tournament = await self.tournament_repository.replace(tournament)
        return await self.refresh_announcement(guild, tournament)

    async def _advance_knockout_if_ready(
        self,
        guild: discord.Guild,
        tournament: TournamentRecord,
        round_label: str,
    ) -> TournamentRecord:
        knockout_matches = await self.match_repository.list_for_phase(guild.id, tournament.tournament_number, TournamentPhase.KNOCKOUT)
        current_round = [match for match in knockout_matches if match.round_label == round_label]
        if not current_round or any(match.status != TournamentMatchStatus.COMPLETED for match in current_round):
            return tournament
        winners = [match.winner_team_id for match in current_round if match.winner_team_id is not None]
        if round_label == "Final" and len(winners) == 1:
            champion_team = await self.team_repository.get(guild.id, tournament.tournament_number, winners[0])
            runner_up_match = current_round[0]
            runner_up_id = runner_up_match.team2_id if winners[0] == runner_up_match.team1_id else runner_up_match.team1_id
            runner_up_team = await self.team_repository.get(guild.id, tournament.tournament_number, runner_up_id)
            if champion_team is None or runner_up_team is None:
                return tournament
            champion_team.status = TournamentTeamStatus.CHAMPION
            runner_up_team.status = TournamentTeamStatus.RUNNER_UP
            await self.team_repository.replace(champion_team)
            await self.team_repository.replace(runner_up_team)
            tournament.phase = TournamentPhase.COMPLETED
            tournament.completed_at = utcnow()
            tournament.champion_team_id = champion_team.team_number
            tournament.runner_up_team_id = runner_up_team.team_number
            tournament = await self.tournament_repository.replace(tournament)
            tournament = await self.refresh_announcement(guild, tournament)
            channel = guild.get_channel(tournament.announcement_channel_id) if tournament.announcement_channel_id else None
            if isinstance(channel, discord.TextChannel):
                await channel.send(embed=build_champion_embed(tournament, champion_team))
            await self.audit_service.log(
                guild,
                AuditAction.TOURNAMENT_COMPLETED,
                f"Tournament #{tournament.tournament_number:03d} completed. Champion: **{champion_team.team_name}**.",
            )
            return tournament
        next_round_label, pairs = self.bracket_service.build_next_round(winners)
        if any(match.round_label == next_round_label for match in knockout_matches):
            return tournament
        for team1_id, team2_id in pairs:
            tournament = await self._create_match_record(
                tournament,
                phase=TournamentPhase.KNOCKOUT,
                round_label=next_round_label,
                team1_id=team1_id,
                team2_id=team2_id,
            )
        return await self.refresh_announcement(guild, tournament)

    def _build_registration_view(self, tournament: TournamentRecord, *, disabled: bool = False):
        from highlight_manager.interactions.tournament_views import TournamentRegistrationView

        return TournamentRegistrationView(self, tournament.tournament_number, disabled=disabled)

    def _build_series_view(self, tournament_number: int, match_number: int, *, disabled: bool = False):
        from highlight_manager.interactions.tournament_views import TournamentSeriesView

        return TournamentSeriesView(self, tournament_number, match_number, disabled=disabled)
