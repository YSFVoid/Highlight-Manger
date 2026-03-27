from __future__ import annotations

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.utils.exceptions import ConfigurationError, UserFacingError
from highlight_manager.utils.permissions import bot_missing_permissions


class VoiceService:
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

        team1 = await guild.create_voice_channel(
            config.team1_voice_name_template.format(match_id=match.display_id),
            category=category,
            user_limit=match.team_size,
            reason=f"Match #{match.display_id} Team 1",
        )
        team2 = await guild.create_voice_channel(
            config.team2_voice_name_template.format(match_id=match.display_id),
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

    async def create_tournament_voice_channels(
        self,
        guild: discord.Guild,
        tournament,
        match,
        config: GuildConfig,
    ) -> tuple[discord.VoiceChannel, discord.VoiceChannel]:
        category = guild.get_channel(config.temp_voice_category_id) if config.temp_voice_category_id else None
        if not isinstance(category, discord.CategoryChannel):
            raise ConfigurationError("Temporary voice category is not configured or no longer exists.")
        missing_perms = bot_missing_permissions(
            guild.me,
            category,
            ["manage_channels", "connect", "view_channel"],
        )
        if missing_perms:
            raise UserFacingError(
                "I am missing permissions to manage tournament voices: " + ", ".join(missing_perms)
            )

        base_name = f"T{tournament.tournament_number:03d}-M{match.match_number:03d}"
        team1 = await guild.create_voice_channel(
            f"{base_name} Team 1",
            category=category,
            reason=f"Tournament Match #{match.match_number:03d} Team 1",
        )
        team2 = await guild.create_voice_channel(
            f"{base_name} Team 2",
            category=category,
            reason=f"Tournament Match #{match.match_number:03d} Team 2",
        )
        return team1, team2

    async def cleanup_tournament_voices(self, guild: discord.Guild, match) -> None:
        for channel_id in [match.team1_voice_channel_id, match.team2_voice_channel_id]:
            if not channel_id:
                continue
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.VoiceChannel):
                try:
                    await channel.delete(reason=f"Cleaning up Tournament Match #{match.match_number:03d}")
                except (discord.Forbidden, discord.HTTPException):
                    continue
