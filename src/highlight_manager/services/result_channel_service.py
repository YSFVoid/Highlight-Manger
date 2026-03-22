from __future__ import annotations

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.enums import ResultChannelBehavior
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.utils.channel_names import format_match_channel_name
from highlight_manager.utils.exceptions import UserFacingError


class ResultChannelService:
    FALLBACK_RESULT_TEMPLATE = "match-{match_id}-result"

    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def _build_overwrites(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
    ) -> dict[discord.Role | discord.Member, discord.PermissionOverwrite]:
        overwrites: dict[discord.Role | discord.Member, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        me = guild.me
        if me:
            overwrites[me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                manage_channels=True,
            )
        for role_id in {*(config.admin_role_ids or []), *(config.staff_role_ids or [])}:
            role = guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

        allowed_user_ids = set(match.all_player_ids) or {match.creator_id}
        for user_id in allowed_user_ids:
            member = guild.get_member(user_id)
            if member:
                overwrites[member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
        return overwrites

    async def _resolve_text_channel(
        self,
        guild: discord.Guild,
        channel_id: int | None,
        *,
        match_number: int,
        purpose: str,
    ) -> discord.TextChannel | None:
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel
        fetch_channel = getattr(guild, "fetch_channel", None)
        if callable(fetch_channel):
            try:
                fetched = await fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, KeyError) as exc:
                self.logger.warning(
                    "result_channel_fetch_failed",
                    guild_id=guild.id,
                    match_number=match_number,
                    channel_id=channel_id,
                    purpose=purpose,
                    error=str(exc),
                )
                return None
            if isinstance(fetched, discord.TextChannel):
                self.logger.info(
                    "result_channel_fetched_from_api",
                    guild_id=guild.id,
                    match_number=match_number,
                    channel_id=channel_id,
                    purpose=purpose,
                )
                return fetched
        self.logger.warning(
            "result_channel_missing_from_cache",
            guild_id=guild.id,
            match_number=match_number,
            channel_id=channel_id,
            purpose=purpose,
        )
        return None

    async def create_private_channel(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
    ) -> discord.TextChannel:
        category = guild.get_channel(config.result_category_id) if config.result_category_id else None
        if category is not None and not isinstance(category, discord.CategoryChannel):
            raise UserFacingError("Configured result category no longer exists.")

        preferred_name = format_match_channel_name(config.result_channel_name_template, match)
        fallback_name = self.FALLBACK_RESULT_TEMPLATE.format(match_id=match.display_id)
        try:
            channel = await guild.create_text_channel(
                name=preferred_name,
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=self._build_overwrites(guild, match, config),
                reason=f"Private result channel for Match #{match.display_id}",
            )
        except discord.HTTPException as exc:
            if exc.status != 400 or preferred_name.casefold() == fallback_name.casefold():
                raise
            self.logger.warning(
                "result_channel_name_fallback_used",
                guild_id=guild.id,
                match_number=match.match_number,
                preferred_name=preferred_name,
                fallback_name=fallback_name,
                error=str(exc),
            )
            channel = await guild.create_text_channel(
                name=fallback_name,
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=self._build_overwrites(guild, match, config),
                reason=f"Private result channel for Match #{match.display_id}",
            )
        self.logger.info(
            "result_channel_created",
            guild_id=guild.id,
            match_number=match.match_number,
            channel_id=channel.id,
        )
        return channel

    async def sync_channel_access(
        self,
        guild: discord.Guild,
        channel_id: int,
        match: MatchRecord,
        config: GuildConfig,
    ) -> None:
        channel = await self._resolve_text_channel(
            guild,
            channel_id,
            match_number=match.match_number,
            purpose="sync_access",
        )
        if channel is None:
            self.logger.warning(
                "result_channel_permission_sync_missing",
                guild_id=guild.id,
                match_number=match.match_number,
                channel_id=channel_id,
            )
            return

        desired_overwrites = self._build_overwrites(guild, match, config)
        desired_user_ids = {
            target.id
            for target in desired_overwrites
            if isinstance(target, discord.Member)
        }
        try:
            for target, overwrite in desired_overwrites.items():
                if channel.overwrites_for(target) == overwrite:
                    continue
                await channel.set_permissions(target, overwrite=overwrite)

            stale_members = [
                target
                for target in channel.overwrites
                if isinstance(target, discord.Member)
                and not target.bot
                and target.id not in desired_user_ids
            ]
            for member in stale_members:
                await channel.set_permissions(member, overwrite=None)

            self.logger.info(
                "result_channel_permissions_synced",
                guild_id=guild.id,
                match_number=match.match_number,
                channel_id=channel.id,
                participant_count=len(match.all_player_ids),
            )
        except discord.HTTPException as exc:
            self.logger.warning(
                "result_channel_permission_sync_failed",
                guild_id=guild.id,
                match_number=match.match_number,
                channel_id=channel.id,
                error=str(exc),
            )

    async def archive_channel(
        self,
        guild: discord.Guild,
        channel_id: int,
        config: GuildConfig,
        match: MatchRecord,
    ) -> None:
        channel = await self._resolve_text_channel(
            guild,
            channel_id,
            match_number=match.match_number,
            purpose="archive",
        )
        if channel is None:
            return
        try:
            for user_id in match.all_player_ids:
                member = guild.get_member(user_id)
                if member:
                    await channel.set_permissions(member, send_messages=False, view_channel=True)
            await channel.edit(name=f"archived-{channel.name}", topic=f"Archived result room for Match #{match.display_id}")
            self.logger.info(
                "result_channel_archived",
                guild_id=guild.id,
                match_number=match.match_number,
                channel_id=channel_id,
                behavior=config.result_channel_behavior.value,
            )
        except discord.Forbidden:
            self.logger.warning(
                "result_channel_archive_forbidden",
                guild_id=guild.id,
                match_number=match.match_number,
                channel_id=channel_id,
            )

    async def delete_channel(self, guild: discord.Guild, channel_id: int, match_number: int) -> None:
        channel = await self._resolve_text_channel(
            guild,
            channel_id,
            match_number=match_number,
            purpose="delete",
        )
        if channel is None:
            return
        try:
            await channel.delete(reason=f"Cleaning up Match #{match_number:03d} result channel")
            self.logger.info(
                "result_channel_deleted",
                guild_id=guild.id,
                match_number=match_number,
                channel_id=channel_id,
            )
        except discord.Forbidden:
            self.logger.warning(
                "result_channel_delete_forbidden",
                guild_id=guild.id,
                match_number=match_number,
                channel_id=channel_id,
            )
        except discord.HTTPException as exc:
            self.logger.warning(
                "result_channel_delete_failed",
                guild_id=guild.id,
                match_number=match_number,
                channel_id=channel_id,
                error=str(exc),
            )

    async def finalize_channel_behavior(
        self,
        guild: discord.Guild,
        match: MatchRecord,
        config: GuildConfig,
    ) -> None:
        if not match.result_channel_id:
            return
        if config.result_channel_behavior == ResultChannelBehavior.ARCHIVE_LOCK:
            await self.archive_channel(guild, match.result_channel_id, config, match)
