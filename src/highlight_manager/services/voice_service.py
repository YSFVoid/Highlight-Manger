from __future__ import annotations

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.utils.channel_names import format_match_channel_name
from highlight_manager.utils.exceptions import ConfigurationError, UserFacingError
from highlight_manager.utils.permissions import bot_missing_permissions


class VoiceService:
    FALLBACK_TEAM1_TEMPLATE = "TEAM 1 - Match #{match_id}"
    FALLBACK_TEAM2_TEMPLATE = "TEAM 2 - Match #{match_id}"

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def ensure_member_in_waiting_voice(self, member: discord.Member, config: GuildConfig) -> None:
        if not config.waiting_voice_channel_id:
            raise ConfigurationError("Waiting Voice channel is not configured.")
        if member.voice is None or member.voice.channel is None:
            raise UserFacingError("You must be in the configured Waiting Voice channel to do that.")
        if member.voice.channel.id != config.waiting_voice_channel_id:
            raise UserFacingError("You must be in the configured Waiting Voice channel to do that.")

    async def create_match_voice_channels(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
    ) -> tuple[discord.VoiceChannel, discord.VoiceChannel]:
        category = guild.get_channel(config.temp_voice_category_id) if config.temp_voice_category_id else None
        if not isinstance(category, discord.CategoryChannel):
            raise ConfigurationError("Temporary voice category is not configured or no longer exists.")
        missing_perms = bot_missing_permissions(
            guild.me,
            category,
            ["manage_channels", "move_members", "connect", "view_channel"],
        )
        if missing_perms:
            raise UserFacingError(
                "I am missing permissions to manage match voices: " + ", ".join(missing_perms)
            )

        team1 = await self._create_voice_channel_with_fallback(
            guild,
            preferred_name=format_match_channel_name(config.team1_voice_name_template, match),
            fallback_name=self.FALLBACK_TEAM1_TEMPLATE.format(match_id=match.display_id),
            category=category,
            user_limit=match.team_size,
            reason=f"Match #{match.display_id} Team 1",
        )
        team2 = await self._create_voice_channel_with_fallback(
            guild,
            preferred_name=format_match_channel_name(config.team2_voice_name_template, match),
            fallback_name=self.FALLBACK_TEAM2_TEMPLATE.format(match_id=match.display_id),
            category=category,
            user_limit=match.team_size,
            reason=f"Match #{match.display_id} Team 2",
        )
        self.logger.info(
            "match_voice_channels_created",
            guild_id=guild.id,
            match_number=match.match_number,
            team1_voice_id=team1.id,
            team2_voice_id=team2.id,
        )
        return team1, team2

    async def move_players_to_team_channels(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        team1_channel: discord.VoiceChannel,
        team2_channel: discord.VoiceChannel,
    ) -> list[str]:
        warnings: list[str] = []
        for user_id, target_channel in [
            *[(user_id, team1_channel) for user_id in match.team1_player_ids],
            *[(user_id, team2_channel) for user_id in match.team2_player_ids],
        ]:
            member = guild.get_member(user_id)
            if member is None:
                warnings.append(f"<@{user_id}> is no longer in the server.")
                continue
            try:
                await member.move_to(target_channel, reason=f"Match #{match.display_id} team assignment")
            except discord.Forbidden:
                warnings.append(f"Could not move {member.mention} because bot lacks Move Members.")
            except discord.HTTPException:
                warnings.append(f"Could not move {member.mention}. They may not be connected.")
        if warnings:
            self.logger.warning(
                "match_player_moves_partial",
                guild_id=guild.id,
                match_number=match.match_number,
                warnings=warnings,
            )
        return warnings

    async def cleanup_match_voices(self, guild: discord.Guild, match: MatchRecord) -> None:
        for channel_id in [match.team1_voice_channel_id, match.team2_voice_channel_id]:
            if not channel_id:
                continue
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.VoiceChannel):
                try:
                    await channel.delete(reason=f"Cleaning up Match #{match.display_id}")
                    self.logger.info(
                        "match_voice_channel_deleted",
                        guild_id=guild.id,
                        match_number=match.match_number,
                        channel_id=channel_id,
                    )
                except discord.Forbidden:
                    self.logger.warning(
                        "match_voice_channel_delete_forbidden",
                        guild_id=guild.id,
                        match_number=match.match_number,
                        channel_id=channel_id,
                    )
                except discord.HTTPException as exc:
                    self.logger.warning(
                        "match_voice_channel_delete_failed",
                        guild_id=guild.id,
                        match_number=match.match_number,
                        channel_id=channel_id,
                        error=str(exc),
                    )

    async def _create_voice_channel_with_fallback(
        self,
        guild: discord.Guild,
        *,
        preferred_name: str,
        fallback_name: str,
        category: discord.CategoryChannel,
        user_limit: int,
        reason: str,
    ) -> discord.VoiceChannel:
        try:
            return await guild.create_voice_channel(
                preferred_name,
                category=category,
                user_limit=user_limit,
                reason=reason,
            )
        except discord.HTTPException as exc:
            if exc.status != 400 or preferred_name.casefold() == fallback_name.casefold():
                raise
            self.logger.warning(
                "voice_channel_name_fallback_used",
                guild_id=guild.id,
                preferred_name=preferred_name,
                fallback_name=fallback_name,
                error=str(exc),
            )
            return await guild.create_voice_channel(
                fallback_name,
                category=category,
                user_limit=user_limit,
                reason=reason,
            )
