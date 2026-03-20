from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.enums import AuditAction, MatchMode, MatchStatus, MatchType, ResultSource
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord, MatchRoomInfo
from highlight_manager.repositories.match_repository import MatchRepository
from highlight_manager.services.audit_service import AuditService
from highlight_manager.services.config_service import ConfigService
from highlight_manager.services.profile_service import ProfileService
from highlight_manager.services.result_channel_service import ResultChannelService
from highlight_manager.services.season_service import SeasonService
from highlight_manager.services.voice_service import VoiceService
from highlight_manager.services.vote_service import VoteService
from highlight_manager.utils.dates import minutes_from_now, seconds_from_now, utcnow
from highlight_manager.utils.embeds import (
    build_match_embed,
    build_match_ready_embed,
    build_match_room_setup_embed,
    build_result_room_embed,
    build_result_summary_embed,
    build_room_info_embed,
    build_vote_status_embed,
)
from highlight_manager.utils.exceptions import HighlightError, StateTransitionError, UserFacingError


@dataclass(slots=True)
class MatchActionResult:
    match: MatchRecord
    message: str


@dataclass(slots=True)
class PlayRequestLogContext:
    raw_command_content: str | None
    raw_mode: str
    raw_type: str
    parsed_mode: str | None = None
    normalized_type: str | None = None
    current_channel_id: int | None = None
    allowed_apostado_channel_id: int | None = None
    allowed_highlight_channel_id: int | None = None
    waiting_voice_id: int | None = None
    member_current_voice_id: int | None = None
    validation_stage: str = "parse_command"

    def as_log_kwargs(self, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "raw_command_content": self.raw_command_content,
            "raw_mode": self.raw_mode,
            "raw_type": self.raw_type,
            "parsed_mode": self.parsed_mode,
            "normalized_type": self.normalized_type,
            "current_channel_id": self.current_channel_id,
            "allowed_apostado_channel_id": self.allowed_apostado_channel_id,
            "allowed_highlight_channel_id": self.allowed_highlight_channel_id,
            "waiting_voice_id": self.waiting_voice_id,
            "member_current_voice_id": self.member_current_voice_id,
            "validation_stage": self.validation_stage,
        }
        payload.update(extra)
        return payload


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
        self.logger = get_logger(__name__)
        self._registered_queue_views: set[tuple[int, int]] = set()
        self._registered_result_views: set[tuple[int, int]] = set()
        self._registered_room_info_views: set[tuple[int, int]] = set()

    async def create_match(
        self,
        channel: discord.abc.Messageable,
        guild: discord.Guild,
        creator: discord.Member,
        mode_input: str,
        type_input: str,
        *,
        raw_command_content: str | None = None,
    ) -> MatchActionResult:
        context = PlayRequestLogContext(
            raw_command_content=raw_command_content,
            raw_mode=mode_input,
            raw_type=type_input,
            current_channel_id=getattr(channel, "id", None),
            member_current_voice_id=(
                creator.voice.channel.id
                if creator.voice is not None and creator.voice.channel is not None
                else None
            ),
        )
        self.logger.info(
            "play_command_received",
            guild_id=guild.id,
            user_id=creator.id,
            **context.as_log_kwargs(validation_result="received"),
        )
        match: MatchRecord | None = None
        public_message: discord.Message | None = None
        result_channel: discord.TextChannel | None = None
        try:
            context.validation_stage = "normalize_type"
            match_type = MatchType.from_input(type_input)
            context.normalized_type = match_type.value
            self.logger.info(
                "play_command_stage_passed",
                guild_id=guild.id,
                user_id=creator.id,
                **context.as_log_kwargs(validation_result="passed"),
            )

            context.validation_stage = "validate_mode"
            mode = MatchMode.from_input(mode_input)
            context.parsed_mode = mode.value
            self.logger.info(
                "play_command_stage_passed",
                guild_id=guild.id,
                user_id=creator.id,
                **context.as_log_kwargs(validation_result="passed"),
            )

            context.validation_stage = "validate_play_channel"
            if not isinstance(channel, discord.abc.GuildChannel):
                raise UserFacingError("Use match commands only in the configured play room.")
            config = await self.config_service.ensure_match_resources(
                guild,
                await self.config_service.get_or_create(guild.id),
            )
            context.allowed_apostado_channel_id = config.apostado_play_channel_id
            context.allowed_highlight_channel_id = config.highlight_play_channel_id
            context.waiting_voice_id = config.waiting_voice_channel_id
            config = await self.config_service.validate_ready_for_matches(guild)
            context.allowed_apostado_channel_id = config.apostado_play_channel_id
            context.allowed_highlight_channel_id = config.highlight_play_channel_id
            context.waiting_voice_id = config.waiting_voice_channel_id
            self.config_service.validate_play_channel(channel, config, match_type)
            self.logger.info(
                "play_command_stage_passed",
                guild_id=guild.id,
                user_id=creator.id,
                **context.as_log_kwargs(validation_result="passed"),
            )

            context.validation_stage = "validate_waiting_voice"
            self.voice_service.ensure_member_in_waiting_voice(creator, config)
            self.logger.info(
                "play_command_stage_passed",
                guild_id=guild.id,
                user_id=creator.id,
                **context.as_log_kwargs(validation_result="passed"),
            )

            context.validation_stage = "validate_eligibility"
            await self.profile_service.require_not_blacklisted(guild, creator.id, config)
            self.logger.info(
                "play_command_stage_passed",
                guild_id=guild.id,
                user_id=creator.id,
                **context.as_log_kwargs(validation_result="passed"),
            )

            context.validation_stage = "reserve_match_number"
            match_number = await self.config_service.reserve_next_match_number(guild.id)

            context.validation_stage = "ensure_active_season"
            season = await self.season_service.ensure_active(guild.id)

            context.validation_stage = "persist_match"
            match = MatchRecord(
                guild_id=guild.id,
                match_number=match_number,
                creator_id=creator.id,
                mode=mode,
                match_type=match_type,
                status=MatchStatus.OPEN,
                team1_player_ids=[creator.id] if config.features.creator_auto_join_team1 else [],
                source_channel_id=channel.id,
                waiting_voice_channel_id=config.waiting_voice_channel_id,
                created_at=utcnow(),
                queue_expires_at=None,
                season_id=season.season_number,
            )
            await self.repository.create(match)

            context.validation_stage = "ensure_private_result_channel"
            try:
                result_channel, created_result_channel = await self._ensure_result_channel(guild, match, config)
                match.result_channel_id = result_channel.id
                await self.result_channel_service.sync_channel_access(guild, result_channel.id, match, config)
                if created_result_channel:
                    await result_channel.send(
                        embed=build_result_room_embed(match, guild),
                        view=self._build_room_info_view(match),
                    )
            except discord.Forbidden as exc:
                await self._cleanup_failed_match_creation(guild, match, public_message, context.validation_stage)
                raise UserFacingError(
                    "I could not create the private match room. Check my channel and permission settings."
                ) from exc
            except discord.HTTPException as exc:
                await self._cleanup_failed_match_creation(guild, match, public_message, context.validation_stage)
                raise UserFacingError(
                    "I could not prepare the private match room right now. Please try again."
                ) from exc

            context.validation_stage = "register_room_setup_view"
            try:
                self.register_views(match)
            except Exception as exc:
                self.logger.warning(
                    "play_command_view_registration_failed",
                    guild_id=guild.id,
                    user_id=creator.id,
                    match_number=match.match_number,
                    error=str(exc),
                    **context.as_log_kwargs(validation_result="warning"),
                )

            context.validation_stage = "post_room_setup_message"
            try:
                public_message = await channel.send(
                    embed=build_match_room_setup_embed(match, guild),
                    view=self._build_room_info_view(match),
                )
            except discord.Forbidden as exc:
                await self._cleanup_failed_match_creation(guild, match, public_message, context.validation_stage)
                raise UserFacingError(
                    "I could not post the room setup card in this room. Check my Send Messages and Embed Links permissions."
                ) from exc
            except discord.HTTPException as exc:
                await self._cleanup_failed_match_creation(guild, match, public_message, context.validation_stage)
                raise UserFacingError(
                    "I could not publish the room setup card in this room right now. Please try again."
                ) from exc

            context.validation_stage = "persist_room_setup_message"
            match.public_message_id = public_message.id
            match = await self.repository.replace(match)

            context.validation_stage = "audit_log"
            try:
                await self.audit_service.log(
                    guild,
                    AuditAction.MATCH_CREATED,
                    f"{creator.mention} created Match #{match.display_id} ({match.mode.value} {match.match_type.label}).",
                    actor_id=creator.id,
                    metadata={"match_number": match.match_number, "type": match.match_type.value, "mode": match.mode.value},
                )
            except Exception as exc:
                self.logger.warning(
                    "play_command_audit_log_failed",
                    guild_id=guild.id,
                    user_id=creator.id,
                    match_number=match.match_number,
                    error=str(exc),
                    **context.as_log_kwargs(validation_result="warning"),
                )
            self.logger.info(
                "play_command_completed",
                guild_id=guild.id,
                user_id=creator.id,
                match_number=match.match_number,
                match_display_id=match.display_id,
                **context.as_log_kwargs(validation_result="success"),
            )
            return MatchActionResult(
                match=match,
                message=f"Match #{match.display_id} is waiting for room info. Use the button in the setup card to open the queue.",
            )
        except HighlightError as exc:
            self.logger.warning(
                "play_command_validation_failed",
                guild_id=guild.id,
                user_id=creator.id,
                error=str(exc),
                **context.as_log_kwargs(validation_result="failed"),
            )
            raise
        except Exception:
            if match is not None and context.validation_stage in {
                "persist_match",
                "ensure_private_result_channel",
                "post_room_setup_message",
                "persist_room_setup_message",
            }:
                await self._cleanup_failed_match_creation(guild, match, public_message, context.validation_stage)
            self.logger.exception(
                "play_command_unexpected_failure",
                guild_id=guild.id,
                user_id=creator.id,
                match_number=match.match_number if match is not None else None,
                **context.as_log_kwargs(validation_result="error"),
            )
            raise

    async def join_team(self, member: discord.Member, match_number: int, team_number: int) -> MatchActionResult:
        config = await self.config_service.ensure_match_resources(
            member.guild,
            await self.config_service.get_or_create(member.guild.id),
        )
        config = await self.config_service.validate_ready_for_matches(member.guild)
        await self.profile_service.require_not_blacklisted(member.guild, member.id, config)
        self.voice_service.ensure_member_in_waiting_voice(member, config)
        match = await self.require_match(member.guild.id, match_number)
        if match.status != MatchStatus.OPEN:
            raise StateTransitionError("That match is no longer open for joining.")
        if match.queue_opened_at is None:
            raise StateTransitionError("This match is still waiting for room info before players can join.")
        if member.id in match.all_player_ids:
            raise UserFacingError("You are already in this match.")

        target_team = match.team1_player_ids if team_number == 1 else match.team2_player_ids
        if len(target_team) >= match.team_size:
            raise UserFacingError(f"Team {team_number} is already full.")

        target_team.append(member.id)
        match = await self.repository.replace(match)
        await self._sync_result_channel_access(member.guild, match, config)
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
            await self.start_full_match(member.guild, match, config)
            return MatchActionResult(match=match, message=f"Match #{match.display_id} is now full.")

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
        config = await self.config_service.get_or_create(member.guild.id)
        await self._sync_result_channel_access(member.guild, match, config)
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
        match.metadata["cancel_reason"] = reason
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

    async def start_full_match(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
        *,
        resume: bool = False,
    ) -> MatchRecord:
        warnings: list[str] = []
        result_channel: discord.TextChannel | None = None
        created_result_channel = False
        try:
            team1_channel, team2_channel = await self._ensure_match_voice_channels(guild, match, config)
            match.team1_voice_channel_id = team1_channel.id
            match.team2_voice_channel_id = team2_channel.id
            warnings.extend(
                await self.voice_service.move_players_to_team_channels(guild, match, team1_channel, team2_channel)
            )
        except Exception as exc:
            warnings.append(str(exc))
            self.logger.warning("full_match_voice_setup_failed", guild_id=guild.id, match_number=match.match_number, error=str(exc))

        try:
            result_channel, created_result_channel = await self._ensure_result_channel(guild, match, config)
            match.result_channel_id = result_channel.id
            await self.result_channel_service.sync_channel_access(guild, result_channel.id, match, config)
        except Exception as exc:
            warnings.append(f"Could not create private result channel: {exc}")
            self.logger.warning("result_channel_creation_failed", guild_id=guild.id, match_number=match.match_number, error=str(exc))

        match.status = MatchStatus.IN_PROGRESS
        match.vote_expires_at = match.vote_expires_at or minutes_from_now(config.vote_timeout_minutes)
        match = await self.repository.replace(match)
        self.register_views(match)
        await self.refresh_match_message(guild, match)

        if result_channel is not None:
            if created_result_channel:
                await result_channel.send(
                    embed=build_result_room_embed(match, guild),
                    view=self._build_result_view(match),
                )
            elif resume:
                await result_channel.send(
                    "Bot restarted while this match was moving into play. Voting controls have been restored.",
                    view=self._build_result_view(match),
                )
            if warnings:
                await result_channel.send("\n".join(warnings))
        match = await self._ensure_room_info_available_in_result_channel(guild, match)
        match = await self._announce_match_ready_if_needed(guild, match, config)
        await self.audit_service.log(
            guild,
            AuditAction.MATCH_FULL,
            f"Match #{match.display_id} is full and moved to active play.",
            metadata={"match_number": match.match_number, "warnings": warnings, "resume": resume},
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
                await self.start_full_match(guild, match, config, resume=True)
                continue
            if match.team1_voice_channel_id and not isinstance(guild.get_channel(match.team1_voice_channel_id), discord.VoiceChannel):
                match.team1_voice_channel_id = None
            if match.team2_voice_channel_id and not isinstance(guild.get_channel(match.team2_voice_channel_id), discord.VoiceChannel):
                match.team2_voice_channel_id = None
            if match.status == MatchStatus.OPEN:
                await self.refresh_match_message(guild, match)
                continue
            result_channel: discord.TextChannel | None = None
            if match.result_channel_id:
                channel = guild.get_channel(match.result_channel_id)
                if isinstance(channel, discord.TextChannel):
                    result_channel = channel
                else:
                    match.result_channel_id = None
            if result_channel is None:
                try:
                    result_channel, _ = await self._ensure_result_channel(guild, match, config)
                    match.result_channel_id = result_channel.id
                except Exception as exc:
                    self.logger.warning(
                        "active_match_result_recovery_failed",
                        guild_id=guild.id,
                        match_number=match.match_number,
                        error=str(exc),
                    )
            match = await self.repository.replace(match)
            await self._sync_result_channel_access(guild, match, config)
            await self.refresh_match_message(guild, match)
            if match.status == MatchStatus.OPEN and match.room_info is not None and match.queue_opened_at is None:
                try:
                    match = await self._open_public_queue_after_room_info(guild, match, config)
                except Exception as exc:
                    self.logger.warning(
                        "pending_queue_open_recovery_failed",
                        guild_id=guild.id,
                        match_number=match.match_number,
                        error=str(exc),
                    )
            if match.status in {MatchStatus.IN_PROGRESS, MatchStatus.VOTING}:
                match = await self._announce_match_ready_if_needed(guild, match, config)
            match = await self._ensure_room_info_available_in_result_channel(guild, match)
            if result_channel is not None:
                await result_channel.send(
                    "Bot restarted. Voting controls have been restored.",
                    view=self._build_result_view(match),
                )

    async def cleanup_stale_resources(self) -> None:
        for match in await self.repository.list_closed_with_voice_channels():
            guild = self.bot.get_guild(match.guild_id)
            if guild is None:
                continue
            await self.voice_service.cleanup_match_voices(guild, match)
            match.team1_voice_channel_id = None
            match.team2_voice_channel_id = None
            await self.repository.replace(match)

    async def handle_waiting_voice_departure(self, member: discord.Member) -> None:
        open_matches = await self.repository.find_open_matches_for_player(member.guild.id, member.id)
        for match in open_matches:
            try:
                await self.leave_open_match(member, match.match_number, triggered_by_voice=True)
                await self.post_public_note(member.guild, match, f"{member.mention} was removed after leaving the Waiting Voice.")
            except Exception as exc:
                self.logger.warning("waiting_voice_departure_cleanup_failed", guild_id=member.guild.id, match_number=match.match_number, user_id=member.id, error=str(exc))

    async def force_close(self, guild: discord.Guild, match_number: int, actor_id: int | None, reason: str) -> MatchActionResult:
        return await self.cancel_match(guild, match_number, actor_id=actor_id, force=True, reason=reason)

    async def submit_room_info(
        self,
        guild: discord.Guild,
        match_number: int,
        actor: discord.Member,
        *,
        room_id: str,
        password: str | None,
        private_match_key: str | None,
    ) -> MatchActionResult:
        match = await self.require_match(guild.id, match_number)
        if match.status not in {MatchStatus.OPEN, MatchStatus.FULL, MatchStatus.IN_PROGRESS, MatchStatus.VOTING}:
            raise StateTransitionError("Room info can only be submitted for an active match.")
        if actor.id != match.creator_id and not await self.config_service.is_staff(actor):
            raise UserFacingError("Only the match creator or staff can submit room info.")

        config = await self.config_service.get_or_create(guild.id)
        normalized_room_id = room_id.strip()
        normalized_password = password.strip() if password else None
        normalized_key = private_match_key.strip() if private_match_key else None
        if not normalized_room_id.isdigit():
            self.logger.warning(
                "room_info_validation_failed",
                guild_id=guild.id,
                match_number=match.match_number,
                actor_id=actor.id,
                validation_error="room_id_not_numeric",
            )
            raise UserFacingError("Room ID must contain numbers only.")
        if config.private_match_key_required and not normalized_key:
            self.logger.warning(
                "room_info_validation_failed",
                guild_id=guild.id,
                match_number=match.match_number,
                actor_id=actor.id,
                validation_error="missing_private_match_key",
            )
            raise UserFacingError("Private Match Key is required before this room info can be saved.")

        was_edit = match.room_info is not None
        if was_edit and match.room_info is not None:
            room_info = match.room_info.model_copy(
                update={
                    "room_id": normalized_room_id,
                    "password": normalized_password or None,
                    "private_match_key": normalized_key or None,
                    "updated_by": actor.id,
                    "updated_at": utcnow(),
                }
            )
        else:
            room_info = MatchRoomInfo(
                room_id=normalized_room_id,
                password=normalized_password or None,
                private_match_key=normalized_key or None,
                submitted_by=actor.id,
            )
        match.room_info = room_info
        if not match.result_channel_id:
            result_channel, _ = await self._ensure_result_channel(guild, match, config)
            match.result_channel_id = result_channel.id
        await self._sync_result_channel_access(guild, match, config)
        match = await self.repository.replace(match)
        match = await self._ensure_room_info_available_in_result_channel(guild, match, force_post=True)
        queue_opened_now = False
        if match.queue_opened_at is None:
            match = await self._open_public_queue_after_room_info(guild, match, config)
            queue_opened_now = True
        else:
            await self.refresh_match_message(guild, match)
            await self.post_public_note(
                guild,
                match,
                f"Room details for Match #{match.display_id} were updated and shared privately.",
            )
        self.logger.info(
            "room_info_saved",
            guild_id=guild.id,
            match_number=match.match_number,
            actor_id=actor.id,
            edited=was_edit,
            queue_opened_now=queue_opened_now,
            has_password=bool(room_info.password),
            has_private_match_key=bool(room_info.private_match_key),
        )
        await self.audit_service.log(
            guild,
            AuditAction.ROOM_INFO_UPDATED,
            (
                f"{actor.mention} {'updated' if was_edit else 'submitted'} room info "
                f"for Match #{match.display_id}."
            ),
            actor_id=actor.id,
            metadata={
                "match_number": match.match_number,
                "edited": was_edit,
                "has_password": bool(room_info.password),
                "private_match_key_provided": bool(room_info.private_match_key),
            },
        )
        return MatchActionResult(
            match=match,
            message=(
                f"Room info saved and Match #{match.display_id} is now open for players."
                if queue_opened_now
                else f"Room info {'updated' if was_edit else 'saved'} for Match #{match.display_id}."
            ),
        )

    async def require_match(self, guild_id: int, match_number: int) -> MatchRecord:
        match = await self.repository.get(guild_id, match_number)
        if match is None:
            raise UserFacingError(f"Match #{match_number:03d} was not found.")
        return match

    def register_views(self, match: MatchRecord) -> None:
        match_key = (match.guild_id, match.match_number)
        if match.queue_opened_at is not None and match_key not in self._registered_queue_views:
            self.bot.add_view(self._build_queue_view(match))
            self._registered_queue_views.add(match_key)
        if match.status in {MatchStatus.IN_PROGRESS, MatchStatus.VOTING, MatchStatus.FULL} and match_key not in self._registered_result_views:
            self.bot.add_view(self._build_result_view(match))
            self._registered_result_views.add(match_key)
        if match.status in {MatchStatus.OPEN, MatchStatus.FULL, MatchStatus.IN_PROGRESS, MatchStatus.VOTING} and match_key not in self._registered_room_info_views:
            self.bot.add_view(self._build_room_info_view(match))
            self._registered_room_info_views.add(match_key)

    async def refresh_match_message(self, guild: discord.Guild, match: MatchRecord) -> None:
        if not match.public_message_id or not match.source_channel_id:
            return
        channel = guild.get_channel(match.source_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        try:
            message = await channel.fetch_message(match.public_message_id)
            if match.status == MatchStatus.OPEN and match.queue_opened_at is None:
                await message.edit(
                    embed=build_match_room_setup_embed(match, guild),
                    view=self._build_room_info_view(match),
                )
            elif match.status == MatchStatus.OPEN:
                await message.edit(
                    embed=build_match_embed(match, guild),
                    view=self._build_queue_view(match),
                )
            else:
                await message.edit(embed=build_match_embed(match, guild), view=None)
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

    async def post_room_info_summary(self, guild: discord.Guild, match: MatchRecord) -> bool:
        if not match.result_channel_id or match.room_info is None:
            return False
        channel = guild.get_channel(match.result_channel_id)
        if not isinstance(channel, discord.TextChannel):
            self.logger.warning(
                "room_info_result_channel_missing",
                guild_id=guild.id,
                match_number=match.match_number,
                channel_id=match.result_channel_id,
            )
            return False
        try:
            await channel.send(embed=build_room_info_embed(match, guild))
        except discord.HTTPException as exc:
            self.logger.warning(
                "room_info_post_failed",
                guild_id=guild.id,
                match_number=match.match_number,
                channel_id=channel.id,
                error=str(exc),
            )
            return False
        self.logger.info(
            "room_info_posted",
            guild_id=guild.id,
            match_number=match.match_number,
            channel_id=channel.id,
            has_password=bool(match.room_info.password),
            has_private_match_key=bool(match.room_info.private_match_key),
        )
        return True

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

        return MatchQueueView(
            self,
            match.guild_id,
            match.match_number,
            disabled=match.status != MatchStatus.OPEN or match.queue_opened_at is None,
        )

    def _build_result_view(self, match: MatchRecord):
        from highlight_manager.interactions.views import ResultEntryView

        return ResultEntryView(
            self,
            match.guild_id,
            match.match_number,
            disabled=match.status not in {MatchStatus.IN_PROGRESS, MatchStatus.VOTING},
        )

    def _build_room_info_view(self, match: MatchRecord):
        from highlight_manager.interactions.views import RoomInfoEntryView

        return RoomInfoEntryView(
            self,
            match.guild_id,
            match.match_number,
            disabled=match.status in {MatchStatus.FINALIZED, MatchStatus.CANCELED, MatchStatus.EXPIRED},
        )

    async def _ensure_match_voice_channels(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
    ) -> tuple[discord.VoiceChannel, discord.VoiceChannel]:
        existing_team1 = guild.get_channel(match.team1_voice_channel_id) if match.team1_voice_channel_id else None
        existing_team2 = guild.get_channel(match.team2_voice_channel_id) if match.team2_voice_channel_id else None
        if isinstance(existing_team1, discord.VoiceChannel) and isinstance(existing_team2, discord.VoiceChannel):
            return existing_team1, existing_team2
        if isinstance(existing_team1, discord.VoiceChannel) or isinstance(existing_team2, discord.VoiceChannel):
            await self.voice_service.cleanup_match_voices(guild, match)
            match.team1_voice_channel_id = None
            match.team2_voice_channel_id = None
        return await self.voice_service.create_match_voice_channels(guild, match, config)

    async def _ensure_result_channel(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
    ) -> tuple[discord.TextChannel, bool]:
        existing = guild.get_channel(match.result_channel_id) if match.result_channel_id else None
        if isinstance(existing, discord.TextChannel):
            return existing, False
        return await self.result_channel_service.create_private_channel(guild, match, config), True

    async def _sync_result_channel_access(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
    ) -> None:
        if not match.result_channel_id:
            return
        await self.result_channel_service.sync_channel_access(guild, match.result_channel_id, match, config)

    async def _open_public_queue_after_room_info(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
    ) -> MatchRecord:
        if match.queue_opened_at is not None:
            return match
        if not match.source_channel_id:
            raise UserFacingError("The configured play room for this match is missing.")

        channel = guild.get_channel(match.source_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise UserFacingError("The configured play room for this match is missing.")

        match.queue_opened_at = utcnow()
        match.queue_expires_at = minutes_from_now(config.queue_timeout_minutes)
        match = await self.repository.replace(match)
        self.register_views(match)

        queue_message: discord.Message | None = None
        if match.public_message_id:
            try:
                queue_message = await channel.fetch_message(match.public_message_id)
                await queue_message.edit(
                    embed=build_match_embed(match, guild),
                    view=self._build_queue_view(match),
                )
            except discord.NotFound:
                self.logger.warning(
                    "room_setup_message_missing_before_queue_open",
                    guild_id=guild.id,
                    match_number=match.match_number,
                    message_id=match.public_message_id,
                )
                match.public_message_id = None
            except discord.HTTPException as exc:
                self.logger.warning(
                    "room_setup_message_update_failed",
                    guild_id=guild.id,
                    match_number=match.match_number,
                    message_id=match.public_message_id,
                    error=str(exc),
                )

        if match.public_message_id is None:
            queue_message = await channel.send(
                embed=build_match_embed(match, guild),
                view=self._build_queue_view(match),
            )
            match.public_message_id = queue_message.id

        if config.ping_here_on_match_create and not match.create_here_ping_sent:
            try:
                await self._send_match_here_ping(guild, match, stage="create")
                match.create_here_ping_sent = True
            except Exception as exc:
                self.logger.warning(
                    "match_create_here_ping_failed",
                    guild_id=guild.id,
                    match_number=match.match_number,
                    error=str(exc),
                )

        match = await self.repository.replace(match)
        self.logger.info(
            "match_queue_opened_after_room_info",
            guild_id=guild.id,
            match_number=match.match_number,
            channel_id=channel.id,
            public_message_id=match.public_message_id,
        )
        await self.audit_service.log(
            guild,
            AuditAction.MATCH_NOTIFICATION,
            f"Opened the public queue for Match #{match.display_id} after room info submission.",
            metadata={"match_number": match.match_number},
        )
        return match

    async def _cleanup_failed_match_creation(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        public_message: discord.Message | None,
        validation_stage: str,
    ) -> None:
        if public_message is not None:
            try:
                await public_message.delete()
            except discord.HTTPException as exc:
                self.logger.warning(
                    "failed_match_public_message_cleanup_failed",
                    guild_id=guild.id,
                    match_number=match.match_number,
                    message_id=public_message.id,
                    validation_stage=validation_stage,
                    error=str(exc),
                )
        if match.result_channel_id:
            await self.result_channel_service.delete_channel(guild, match.result_channel_id, match.match_number)
        deleted = False
        delete_match = getattr(self.repository, "delete", None)
        if callable(delete_match):
            deleted = await delete_match(match.guild_id, match.match_number)
        self.logger.info(
            "failed_match_creation_cleaned_up",
            guild_id=guild.id,
            match_number=match.match_number,
            validation_stage=validation_stage,
            deleted_from_repository=deleted,
            had_public_message=public_message is not None,
        )

    async def _ensure_room_info_available_in_result_channel(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        *,
        force_post: bool = False,
    ) -> MatchRecord:
        if match.room_info is None or not match.result_channel_id:
            return match
        last_posted_channel_id = match.metadata.get("room_info_posted_channel_id")
        if not force_post and last_posted_channel_id == match.result_channel_id:
            return match
        posted = await self.post_room_info_summary(guild, match)
        if not posted:
            return match
        match.metadata["room_info_posted_channel_id"] = match.result_channel_id
        return await self.repository.replace(match)

    async def _announce_match_ready_if_needed(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
    ) -> MatchRecord:
        if match.ready_announcement_sent or not match.source_channel_id:
            return match
        channel = guild.get_channel(match.source_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return match
        content = "@here" if config.ping_here_on_match_ready and not match.ready_here_ping_sent else None
        try:
            await channel.send(
                content=content,
                embed=build_match_ready_embed(match, guild),
                view=None if match.room_info is not None else self._build_room_info_view(match),
            )
            match.ready_announcement_sent = True
            if content:
                match.ready_here_ping_sent = True
            match = await self.repository.replace(match)
            self.logger.info(
                "match_ready_announced",
                guild_id=guild.id,
                match_number=match.match_number,
                channel_id=channel.id,
                here_ping_sent=bool(content),
            )
            await self.audit_service.log(
                guild,
                AuditAction.MATCH_NOTIFICATION,
                f"Posted the Match Ready announcement for Match #{match.display_id}.",
                metadata={
                    "match_number": match.match_number,
                    "here_ping_sent": bool(content),
                },
            )
        except Exception as exc:
            self.logger.warning(
                "match_ready_announcement_failed",
                guild_id=guild.id,
                match_number=match.match_number,
                channel_id=channel.id,
                error=str(exc),
            )
        return match

    async def _send_match_here_ping(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        *,
        stage: str,
    ) -> None:
        if not match.source_channel_id:
            return
        channel = guild.get_channel(match.source_channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return
        await channel.send("@here")
        self.logger.info(
            "match_here_ping_sent",
            guild_id=guild.id,
            match_number=match.match_number,
            channel_id=channel.id,
            stage=stage,
        )
        await self.audit_service.log(
            guild,
            AuditAction.MATCH_NOTIFICATION,
            f"Sent @here for Match #{match.display_id} during the {stage} stage.",
            metadata={"match_number": match.match_number, "stage": stage},
        )
