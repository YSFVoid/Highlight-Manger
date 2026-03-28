from __future__ import annotations

from dataclasses import dataclass

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.enums import AuditAction, MatchMode, MatchStatus, MatchType, ResultSource
from highlight_manager.models.match import MatchRecord
from highlight_manager.repositories.match_repository import MatchRepository
from highlight_manager.services.audit_service import AuditService
from highlight_manager.services.coins_service import CoinsService
from highlight_manager.services.config_service import ConfigService
from highlight_manager.services.profile_service import ProfileService
from highlight_manager.services.result_channel_service import ResultChannelService
from highlight_manager.services.season_service import SeasonService
from highlight_manager.services.voice_service import VoiceService
from highlight_manager.services.vote_service import VoteService
from highlight_manager.utils.dates import minutes_from_now, seconds_from_now, utcnow
from highlight_manager.utils.embeds import build_match_embed, build_result_summary_embed, build_vote_status_embed
from highlight_manager.utils.exceptions import StateTransitionError, UserFacingError


@dataclass(slots=True)
class MatchActionResult:
    match: MatchRecord
    message: str


class MatchService:
    ACTIVE_STATES = {MatchStatus.OPEN, MatchStatus.FULL, MatchStatus.IN_PROGRESS, MatchStatus.VOTING}

    def __init__(
        self,
        bot: discord.Client,
        repository: MatchRepository,
        config_service: ConfigService,
        profile_service: ProfileService,
        season_service: SeasonService,
        vote_service: VoteService,
        voice_service: VoiceService,
        result_channel_service: ResultChannelService,
        audit_service: AuditService,
        coins_service: CoinsService | None = None,
    ) -> None:
        self.bot = bot
        self.repository = repository
        self.config_service = config_service
        self.profile_service = profile_service
        self.season_service = season_service
        self.vote_service = vote_service
        self.voice_service = voice_service
        self.result_channel_service = result_channel_service
        self.audit_service = audit_service
        self.coins_service = coins_service
        self.logger = get_logger(__name__)

    async def create_match(
        self,
        channel: discord.abc.Messageable,
        guild: discord.Guild,
        creator: discord.Member,
        mode_input: str,
        type_input: str,
    ) -> MatchActionResult:
        mode = MatchMode.from_input(mode_input)
        match_type = MatchType.from_input(type_input)
        config = await self.config_service.ensure_match_resources(guild, await self.config_service.get_or_create(guild.id))
        config = await self.config_service.backfill_play_channels(guild, config)
        config = await self.config_service.validate_ready_for_matches(guild.id)
        self._validate_play_channel(channel, config, match_type)
        await self.profile_service.require_not_blacklisted(guild, creator.id, config)
        self.voice_service.ensure_member_in_waiting_voice(creator, config)

        match_number = await self.config_service.reserve_next_match_number(guild.id)
        season = await self.season_service.ensure_active(guild.id)
        match = MatchRecord(
            guild_id=guild.id,
            match_number=match_number,
            creator_id=creator.id,
            mode=mode,
            match_type=match_type,
            status=MatchStatus.OPEN,
            team1_player_ids=[creator.id] if config.features.creator_auto_join_team1 else [],
            source_channel_id=getattr(channel, "id", None),
            waiting_voice_channel_id=config.waiting_voice_channel_id,
            created_at=utcnow(),
            queue_expires_at=minutes_from_now(config.queue_timeout_minutes),
            season_id=season.season_number,
        )
        await self.repository.create(match)
        self.register_views(match)
        public_message = await channel.send(embed=build_match_embed(match, guild), view=self._build_queue_view(match))
        match.public_message_id = public_message.id
        match = await self.repository.replace(match)
        await self.audit_service.log(
            guild,
            AuditAction.MATCH_CREATED,
            f"{creator.mention} created Match #{match.display_id} ({match.mode.value} {match.match_type.label}).",
            actor_id=creator.id,
            metadata={"match_number": match.match_number, "type": match.match_type.value, "mode": match.mode.value},
        )
        return MatchActionResult(match=match, message=f"Created Match #{match.display_id}.")

    async def join_team(self, member: discord.Member, match_number: int, team_number: int) -> MatchActionResult:
        config = await self.config_service.ensure_match_resources(
            member.guild,
            await self.config_service.get_or_create(member.guild.id),
        )
        config = await self.config_service.validate_ready_for_matches(member.guild.id)
        await self.profile_service.require_not_blacklisted(member.guild, member.id, config)
        self.voice_service.ensure_member_in_waiting_voice(member, config)
        match = await self.require_match(member.guild.id, match_number)
        if match.status != MatchStatus.OPEN:
            raise StateTransitionError("That match is no longer open for joining.")
        if member.id in match.all_player_ids:
            raise UserFacingError("You are already in this match.")

        target_team = match.team1_player_ids if team_number == 1 else match.team2_player_ids
        if len(target_team) >= match.team_size:
            raise UserFacingError(f"Team {team_number} is already full.")

        target_team.append(member.id)
        match = await self.repository.replace(match)
        await self.audit_service.log(
            member.guild,
            AuditAction.MATCH_JOINED,
            f"{member.mention} joined Team {team_number} for Match #{match.display_id}.",
            actor_id=member.id,
            metadata={"match_number": match.match_number, "team": team_number},
        )
        if match.is_full:
            match.status = MatchStatus.FULL
            match.vote_expires_at = minutes_from_now(config.vote_timeout_minutes)
            match = await self.repository.replace(match)
            await self.refresh_match_message(member.guild, match)
            try:
                match = await self.start_full_match(member.guild, match, config)
            except UserFacingError as exc:
                canceled = await self.cancel_match(
                    member.guild,
                    match.match_number,
                    actor_id=None,
                    force=True,
                    reason=f"Automatic match start failed: {exc}",
                )
                await self.post_public_note(
                    member.guild,
                    canceled.match,
                    f"Match #{canceled.match.display_id} was canceled because automatic start failed.\nReason: {exc}",
                )
                return MatchActionResult(
                    match=canceled.match,
                    message=f"Match #{canceled.match.display_id} was canceled because automatic start failed.",
                )
            return MatchActionResult(match=match, message=f"Match #{match.display_id} is now live.")

        await self.refresh_match_message(member.guild, match)
        return MatchActionResult(match=match, message=f"Joined Team {team_number} in Match #{match.display_id}.")

    async def leave_open_match(
        self,
        member: discord.Member,
        match_number: int,
        *,
        triggered_by_voice: bool = False,
    ) -> MatchActionResult:
        match = await self.require_match(member.guild.id, match_number)
        if match.status != MatchStatus.OPEN:
            raise StateTransitionError("You can only leave a match while it is still open.")
        if member.id not in match.all_player_ids:
            raise UserFacingError("You are not in that match.")
        if member.id in match.team1_player_ids:
            match.team1_player_ids.remove(member.id)
        if member.id in match.team2_player_ids:
            match.team2_player_ids.remove(member.id)
        match = await self.repository.replace(match)
        await self.refresh_match_message(member.guild, match)
        if not triggered_by_voice:
            await self.audit_service.log(
                member.guild,
                AuditAction.MATCH_LEFT,
                f"{member.mention} left Match #{match.display_id}.",
                actor_id=member.id,
                metadata={"match_number": match.match_number},
            )
        return MatchActionResult(match=match, message=f"You left Match #{match.display_id}.")

    async def cancel_match(
        self,
        guild: discord.Guild,
        match_number: int,
        *,
        actor_id: int | None,
        force: bool,
        reason: str,
    ) -> MatchActionResult:
        match = await self.require_match(guild.id, match_number)
        if match.status in {MatchStatus.FINALIZED, MatchStatus.CANCELED, MatchStatus.EXPIRED}:
            raise StateTransitionError("That match is already closed.")
        if match.status != MatchStatus.OPEN and not force:
            raise StateTransitionError("This match can only be canceled by admins now.")

        config = await self.config_service.get_or_create(guild.id)
        await self.voice_service.cleanup_match_voices(guild, match)
        await self.vote_service.clear_votes(match)
        match.status = MatchStatus.CANCELED
        match.canceled_at = utcnow()
        match.team1_voice_channel_id = None
        match.team2_voice_channel_id = None
        if match.result_channel_id:
            await self.post_result_note(guild, match, f"Match #{match.display_id} was canceled.\nReason: {reason}")
            if config.result_channel_behavior.value == "DELETE":
                match.result_channel_cleanup_at = seconds_from_now(config.result_channel_delete_delay_seconds)
            else:
                await self.result_channel_service.finalize_channel_behavior(guild, match, config)
        match = await self.repository.replace(match)
        await self.refresh_match_message(guild, match)
        await self.audit_service.log(
            guild,
            AuditAction.MATCH_CANCELED,
            f"Match #{match.display_id} was canceled. Reason: {reason}",
            actor_id=actor_id,
            metadata={"match_number": match.match_number, "reason": reason, "force": force},
        )
        return MatchActionResult(match=match, message=f"Canceled Match #{match.display_id}.")

    async def start_full_match(self, guild: discord.Guild, match: MatchRecord, config) -> MatchRecord:
        self._validate_players_ready_for_start(guild, match, config)
        warnings: list[str] = []
        team1_channel: discord.VoiceChannel | None = None
        team2_channel: discord.VoiceChannel | None = None
        result_channel: discord.TextChannel | None = None
        try:
            team1_channel, team2_channel = await self.voice_service.create_match_voice_channels(guild, match, config)
            result_channel = await self.result_channel_service.create_private_channel(guild, match, config)
            match.team1_voice_channel_id = team1_channel.id
            match.team2_voice_channel_id = team2_channel.id
            match.result_channel_id = result_channel.id
            warnings.extend(
                await self.voice_service.move_players_to_team_channels(guild, match, team1_channel, team2_channel)
            )
        except UserFacingError:
            if result_channel is not None:
                await self.result_channel_service.delete_channel(guild, result_channel.id, match.match_number)
            if team1_channel is not None:
                await self.voice_service.cleanup_match_voices(
                    guild,
                    match.model_copy(
                        update={
                            "team1_voice_channel_id": team1_channel.id,
                            "team2_voice_channel_id": team2_channel.id if team2_channel is not None else None,
                        }
                    ),
                )
            raise
        except Exception as exc:
            if result_channel is not None:
                await self.result_channel_service.delete_channel(guild, result_channel.id, match.match_number)
            if team1_channel is not None:
                await self.voice_service.cleanup_match_voices(
                    guild,
                    match.model_copy(
                        update={
                            "team1_voice_channel_id": team1_channel.id,
                            "team2_voice_channel_id": team2_channel.id if team2_channel is not None else None,
                        }
                    ),
                )
            self.logger.warning(
                "full_match_start_failed",
                guild_id=guild.id,
                match_number=match.match_number,
                error=str(exc),
            )
            raise UserFacingError("I could not create the match voice/result channels. Check setup and bot permissions.") from exc

        match.status = MatchStatus.IN_PROGRESS
        match.vote_expires_at = match.vote_expires_at or minutes_from_now(config.vote_timeout_minutes)
        match = await self.repository.replace(match)
        self.register_views(match)
        await self.refresh_match_message(guild, match)

        await result_channel.send(
            embed=discord.Embed(
                title=f"Result Room | Match #{match.display_id}",
                description=(
                    f"Mode: **{match.mode.value}**\n"
                    f"Type: **{match.match_type.label}**\n"
                    f"Vote deadline: <t:{int(match.vote_expires_at.timestamp())}:R>\n"
                    "When the match ends, every player must submit a result vote here."
                ),
                colour=discord.Colour.orange(),
            ),
            view=self._build_result_view(match),
        )
        if warnings:
            await result_channel.send("\n".join(warnings))
        await self.audit_service.log(
            guild,
            AuditAction.MATCH_FULL,
            f"Match #{match.display_id} is full and moved to active play.",
            metadata={"match_number": match.match_number, "warnings": warnings},
        )
        return match

    async def submit_vote(
        self,
        guild: discord.Guild,
        match_number: int,
        *,
        user_id: int,
        winner_team: int,
        winner_mvp_id: int | None,
        loser_mvp_id: int | None,
    ) -> MatchActionResult:
        match = await self.require_match(guild.id, match_number)
        if match.status not in {MatchStatus.IN_PROGRESS, MatchStatus.VOTING}:
            raise StateTransitionError("Voting is not available for that match.")

        await self.vote_service.submit_vote(
            match,
            user_id=user_id,
            winner_team=winner_team,
            winner_mvp_id=winner_mvp_id,
            loser_mvp_id=loser_mvp_id,
        )
        if match.status == MatchStatus.IN_PROGRESS:
            match.status = MatchStatus.VOTING
            match = await self.repository.replace(match)
            await self.refresh_match_message(guild, match)

        votes = await self.vote_service.get_votes(match)
        await self.post_vote_status(guild, match, votes)
        if len(votes) == len(match.all_player_ids):
            consensus = self.vote_service.compute_consensus(match, votes)
            if consensus:
                finalized = await self.finalize_match(
                    guild,
                    match_number,
                    winner_team=consensus.winner_team,
                    winner_mvp_id=consensus.winner_mvp_id,
                    loser_mvp_id=consensus.loser_mvp_id,
                    source=ResultSource.CONSENSUS,
                    notes="Finalized from player consensus.",
                )
                return MatchActionResult(match=finalized, message=f"Match #{finalized.display_id} finalized.")
            match.needs_admin_review = True
            match = await self.repository.replace(match)
            await self.post_result_note(
                guild,
                match,
                "All votes are in, but no valid consensus could be computed. Waiting for admin review or timeout.",
            )
            return MatchActionResult(match=match, message="Vote recorded. Waiting for admin review or timeout.")

        return MatchActionResult(match=match, message=f"Vote recorded ({len(votes)}/{len(match.all_player_ids)} submitted).")

    async def finalize_match(
        self,
        guild: discord.Guild,
        match_number: int,
        *,
        winner_team: int,
        winner_mvp_id: int | None,
        loser_mvp_id: int | None,
        source: ResultSource,
        actor_id: int | None = None,
        notes: str | None = None,
    ) -> MatchRecord:
        match = await self.require_match(guild.id, match_number)
        if match.status in {MatchStatus.FINALIZED, MatchStatus.CANCELED, MatchStatus.EXPIRED}:
            raise StateTransitionError("That match is already closed.")
        self.vote_service.validate_result_selection(
            match,
            winner_team=winner_team,
            winner_mvp_id=winner_mvp_id,
            loser_mvp_id=loser_mvp_id,
        )
        config = await self.config_service.get_or_create(guild.id)
        summary = await self.profile_service.apply_match_outcome(
            guild,
            match,
            config,
            winner_team=winner_team,
            winner_mvp_id=winner_mvp_id,
            loser_mvp_id=loser_mvp_id,
            source=source,
            notes=notes,
        )
        if self.coins_service is not None and not match.coin_rewards_applied:
            await self.coins_service.award_regular_match_rewards(guild, match, summary)
            match.coin_rewards_applied = True
        await self.voice_service.cleanup_match_voices(guild, match)
        match.status = MatchStatus.FINALIZED
        match.finalized_at = utcnow()
        match.team1_voice_channel_id = None
        match.team2_voice_channel_id = None
        match.penalties_applied = source == ResultSource.VOTE_TIMEOUT
        match.result_summary = summary
        if match.result_channel_id and config.result_channel_behavior.value == "DELETE":
            match.result_channel_cleanup_at = seconds_from_now(config.result_channel_delete_delay_seconds)
        match = await self.repository.replace(match)
        await self.refresh_match_message(guild, match)
        await self.post_result_summary(guild, match)
        await self.result_channel_service.finalize_channel_behavior(guild, match, config)
        await self.audit_service.log(
            guild,
            AuditAction.MATCH_FINALIZED,
            f"Match #{match.display_id} finalized.",
            actor_id=actor_id,
            metadata={
                "match_number": match.match_number,
                "source": source.value,
                "winner_team": winner_team,
                "winner_mvp_id": winner_mvp_id,
                "loser_mvp_id": loser_mvp_id,
            },
        )
        return match

    async def expire_vote_timeout(self, guild: discord.Guild, match: MatchRecord) -> MatchRecord:
        config = await self.config_service.get_or_create(guild.id)
        summary = await self.profile_service.apply_vote_timeout_penalty(
            guild,
            match,
            config,
            notes="Voting timed out before a valid consensus or force result was recorded.",
        )
        await self.voice_service.cleanup_match_voices(guild, match)
        match.status = MatchStatus.EXPIRED
        match.penalties_applied = True
        match.team1_voice_channel_id = None
        match.team2_voice_channel_id = None
        match.finalized_at = utcnow()
        match.result_summary = summary
        if match.result_channel_id and config.result_channel_behavior.value == "DELETE":
            match.result_channel_cleanup_at = seconds_from_now(config.result_channel_delete_delay_seconds)
        match = await self.repository.replace(match)
        await self.refresh_match_message(guild, match)
        await self.post_result_summary(guild, match)
        await self.result_channel_service.finalize_channel_behavior(guild, match, config)
        await self.audit_service.log(
            guild,
            AuditAction.MATCH_EXPIRED,
            f"Match #{match.display_id} expired because voting timed out.",
            metadata={"match_number": match.match_number},
        )
        return match

    async def process_due_events(self) -> None:
        now = utcnow()
        for match in await self.repository.list_due_queue_expirations(now):
            guild = self.bot.get_guild(match.guild_id)
            if guild is None:
                continue
            try:
                await self.cancel_match(
                    guild,
                    match.match_number,
                    actor_id=None,
                    force=True,
                    reason="Queue timed out before the match filled.",
                )
            except Exception as exc:
                self.logger.warning("queue_expiration_processing_failed", guild_id=match.guild_id, match_number=match.match_number, error=str(exc))

        for match in await self.repository.list_due_vote_expirations(now):
            guild = self.bot.get_guild(match.guild_id)
            if guild is None:
                continue
            try:
                await self.expire_vote_timeout(guild, match)
            except Exception as exc:
                self.logger.warning("vote_expiration_processing_failed", guild_id=match.guild_id, match_number=match.match_number, error=str(exc))

        for match in await self.repository.list_due_result_cleanup(now):
            guild = self.bot.get_guild(match.guild_id)
            if guild is None or not match.result_channel_id:
                continue
            await self.result_channel_service.delete_channel(guild, match.result_channel_id, match.match_number)
            match.result_channel_id = None
            match.result_channel_cleanup_at = None
            await self.repository.replace(match)

    async def reconcile_active_matches(self) -> None:
        matches = await self.repository.list_active(statuses=list(self.ACTIVE_STATES))
        for match in matches:
            guild = self.bot.get_guild(match.guild_id)
            if guild is None:
                continue
            config = await self.config_service.get_or_create(guild.id)
            self.register_views(match)
            if match.status == MatchStatus.FULL:
                try:
                    match = await self.start_full_match(guild, match, config)
                except UserFacingError as exc:
                    await self.cancel_match(
                        guild,
                        match.match_number,
                        actor_id=None,
                        force=True,
                        reason=f"Restart recovery failed to start full match: {exc}",
                    )
            if match.status in {MatchStatus.IN_PROGRESS, MatchStatus.VOTING} and match.result_channel_id:
                channel = guild.get_channel(match.result_channel_id)
                if isinstance(channel, discord.TextChannel):
                    await channel.send("Bot restarted. Voting controls have been restored.", view=self._build_result_view(match))

    async def handle_waiting_voice_departure(self, member: discord.Member) -> None:
        open_matches = await self.repository.find_open_matches_for_player(member.guild.id, member.id)
        for match in open_matches:
            try:
                if member.id == match.creator_id:
                    await self.cancel_match(
                        member.guild,
                        match.match_number,
                        actor_id=None,
                        force=True,
                        reason="Creator left the Waiting Voice before the match started.",
                    )
                    await self.post_public_note(
                        member.guild,
                        match,
                        f"Match #{match.display_id} was canceled because the creator left the Waiting Voice.",
                    )
                    continue
                await self.leave_open_match(member, match.match_number, triggered_by_voice=True)
                await self.post_public_note(member.guild, match, f"{member.mention} was removed after leaving the Waiting Voice.")
            except Exception as exc:
                self.logger.warning("waiting_voice_departure_cleanup_failed", guild_id=member.guild.id, match_number=match.match_number, user_id=member.id, error=str(exc))

    async def force_close(self, guild: discord.Guild, match_number: int, actor_id: int | None, reason: str) -> MatchActionResult:
        return await self.cancel_match(guild, match_number, actor_id=actor_id, force=True, reason=reason)

    async def cancel_result_room_match(self, guild: discord.Guild, match_number: int, actor: discord.Member) -> MatchActionResult:
        match = await self.require_match(guild.id, match_number)
        if match.status in {MatchStatus.FINALIZED, MatchStatus.CANCELED, MatchStatus.EXPIRED}:
            raise StateTransitionError("That match is already closed.")
        is_staff = await self.config_service.is_staff(actor)
        if actor.id != match.creator_id and not is_staff:
            raise UserFacingError("Only the creator or staff can cancel this match.")

        reason: str
        if is_staff:
            reason = "Canceled by staff from the result room."
        else:
            votes = await self.vote_service.get_votes(match)
            if votes:
                raise StateTransitionError("Once result voting starts, only staff can cancel this match.")
            if match.status not in {MatchStatus.IN_PROGRESS, MatchStatus.VOTING, MatchStatus.FULL}:
                raise StateTransitionError("The creator can only cancel while the match is active.")
            reason = "Canceled by the creator before result voting started."

        result = await self.cancel_match(
            guild,
            match_number,
            actor_id=actor.id,
            force=True,
            reason=reason,
        )
        await self.post_public_note(guild, result.match, f"Match #{result.match.display_id} was canceled. Reason: {reason}")
        return result

    async def require_match(self, guild_id: int, match_number: int) -> MatchRecord:
        match = await self.repository.get(guild_id, match_number)
        if match is None:
            raise UserFacingError(f"Match #{match_number:03d} was not found.")
        return match

    def register_views(self, match: MatchRecord) -> None:
        self.bot.add_view(self._build_queue_view(match))
        if match.status in {MatchStatus.IN_PROGRESS, MatchStatus.VOTING, MatchStatus.FULL}:
            self.bot.add_view(self._build_result_view(match))

    async def refresh_match_message(self, guild: discord.Guild, match: MatchRecord) -> None:
        if not match.public_message_id or not match.source_channel_id:
            return
        channel = guild.get_channel(match.source_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            message = await channel.fetch_message(match.public_message_id)
            await message.edit(embed=build_match_embed(match, guild), view=self._build_queue_view(match))
        except discord.NotFound:
            self.logger.warning("match_public_message_missing", guild_id=guild.id, match_number=match.match_number, message_id=match.public_message_id)
        except discord.HTTPException as exc:
            self.logger.warning("match_public_message_refresh_failed", guild_id=guild.id, match_number=match.match_number, error=str(exc))

    async def post_vote_status(self, guild: discord.Guild, match: MatchRecord, votes) -> None:
        if not match.result_channel_id:
            return
        channel = guild.get_channel(match.result_channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=build_vote_status_embed(match, guild, votes), view=self._build_result_view(match))

    async def post_result_summary(self, guild: discord.Guild, match: MatchRecord) -> None:
        if not match.result_channel_id:
            return
        channel = guild.get_channel(match.result_channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=build_result_summary_embed(match, guild))

    async def post_result_note(self, guild: discord.Guild, match: MatchRecord, message: str) -> None:
        if not match.result_channel_id:
            return
        channel = guild.get_channel(match.result_channel_id)
        if isinstance(channel, discord.TextChannel):
            await channel.send(message)

    async def post_public_note(self, guild: discord.Guild, match: MatchRecord, message: str) -> None:
        if not match.source_channel_id:
            return
        channel = guild.get_channel(match.source_channel_id)
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            await channel.send(message)

    def _build_queue_view(self, match: MatchRecord):
        from highlight_manager.interactions.views import MatchQueueView

        return MatchQueueView(self, match.match_number, disabled=match.status != MatchStatus.OPEN)

    def _build_result_view(self, match: MatchRecord):
        from highlight_manager.interactions.views import ResultEntryView

        return ResultEntryView(self, match.match_number, disabled=match.status not in {MatchStatus.IN_PROGRESS, MatchStatus.VOTING})

    def _validate_play_channel(self, channel: discord.abc.Messageable, config, match_type: MatchType) -> None:
        channel_id = getattr(channel, "id", None)
        expected_channel_id = (
            config.apostado_channel_id
            if match_type == MatchType.APOSTADO
            else config.highlight_channel_id
        )
        if expected_channel_id and channel_id != expected_channel_id:
            label = match_type.label
            raise UserFacingError(f"{label} matches can only be created in <#{expected_channel_id}>.")

    def _validate_players_ready_for_start(self, guild: discord.Guild, match: MatchRecord, config) -> None:
        waiting_voice_id = config.waiting_voice_channel_id
        if not waiting_voice_id:
            raise UserFacingError("Waiting Voice channel is not configured.")
        for user_id in match.all_player_ids:
            member = guild.get_member(user_id)
            if member is None:
                raise UserFacingError(f"<@{user_id}> is no longer in the server.")
            current_voice_id = member.voice.channel.id if member.voice and member.voice.channel else None
            if current_voice_id != waiting_voice_id:
                raise UserFacingError(f"{member.display_name} must stay in the Waiting Voice until the bot moves players.")
