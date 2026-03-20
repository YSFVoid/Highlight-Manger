from __future__ import annotations

from typing import Any

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.config.settings import Settings
from highlight_manager.models.enums import MatchType
from highlight_manager.models.guild_config import GuildConfig, fallback_resource_names
from highlight_manager.repositories.config_repository import ConfigRepository
from highlight_manager.utils.exceptions import ConfigurationError, UserFacingError
from highlight_manager.utils.permissions import member_has_any_role


class ConfigService:
    def __init__(self, repository: ConfigRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.logger = get_logger(__name__)

    def build_default_config(self, guild_id: int) -> GuildConfig:
        return GuildConfig(
            guild_id=guild_id,
            prefix=self.settings.default_prefix,
            result_channel_delete_delay_seconds=self.settings.result_channel_delete_delay_seconds,
        )

    async def get(self, guild_id: int) -> GuildConfig | None:
        return await self.repository.get(guild_id)

    async def get_or_create(self, guild_id: int) -> GuildConfig:
        existing = await self.repository.get(guild_id)
        if existing:
            return existing
        defaults = self.build_default_config(guild_id)
        return await self.repository.upsert(defaults)

    def resolve_configured_channel(
        self,
        guild: discord.Guild,
        channel_id: int | None,
        *,
        resource_key: str,
        expected_types: type[discord.abc.GuildChannel] | tuple[type[discord.abc.GuildChannel], ...],
    ) -> discord.abc.GuildChannel | None:
        channel = guild.get_channel(channel_id) if channel_id else None
        resolved = channel is not None and isinstance(channel, expected_types)
        expected_names = expected_types if isinstance(expected_types, tuple) else (expected_types,)
        self.logger.info(
            "config_resource_lookup",
            guild_id=getattr(guild, "id", None),
            resource_key=resource_key,
            resource_id=channel_id,
            resolved=resolved,
            actual_type=type(channel).__name__ if channel is not None else None,
            expected_types=[item.__name__ for item in expected_names],
        )
        if resolved:
            return channel
        if channel is not None:
            self.logger.warning(
                "config_resource_type_mismatch",
                guild_id=getattr(guild, "id", None),
                resource_key=resource_key,
                resource_id=channel_id,
                actual_type=type(channel).__name__,
                expected_types=[item.__name__ for item in expected_names],
            )
        return None

    def resolve_configured_role(
        self,
        guild: discord.Guild,
        role_id: int | None,
        *,
        resource_key: str,
    ) -> discord.Role | None:
        role = guild.get_role(role_id) if role_id else None
        self.logger.info(
            "config_role_lookup",
            guild_id=getattr(guild, "id", None),
            resource_key=resource_key,
            resource_id=role_id,
            resolved=role is not None,
        )
        return role

    async def update(self, guild_id: int, updates: dict[str, Any]) -> GuildConfig:
        config = await self.get_or_create(guild_id)
        merged = config.model_copy(update=updates)
        return await self.repository.upsert(merged)

    async def reserve_next_match_number(self, guild_id: int) -> int:
        defaults = await self.get_or_create(guild_id)
        return await self.repository.reserve_next_match_number(guild_id, defaults)

    async def is_staff(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        config = await self.get_or_create(member.guild.id)
        role_ids = list({*config.admin_role_ids, *config.staff_role_ids})
        return member_has_any_role(member, role_ids)

    async def ensure_match_resources(self, guild: discord.Guild, config: GuildConfig) -> GuildConfig:
        updates: dict[str, Any] = {}
        created = dict(config.setup_created_resources)
        fallback_names = fallback_resource_names()
        waiting_exists = (
            self.resolve_configured_channel(
                guild,
                config.waiting_voice_channel_id,
                resource_key="waiting_voice_channel_id",
                expected_types=discord.VoiceChannel,
            )
            is not None
        )
        temp_exists = (
            self.resolve_configured_channel(
                guild,
                config.temp_voice_category_id,
                resource_key="temp_voice_category_id",
                expected_types=discord.CategoryChannel,
            )
            is not None
        )

        if config.features.auto_create_waiting_voice and not waiting_exists:
            waiting = await self._create_voice_channel_with_fallback(
                guild,
                name=config.resource_names.waiting_voice,
                fallback_name=fallback_names.waiting_voice,
                reason="Highlight Manager setup",
            )
            updates["waiting_voice_channel_id"] = waiting.id
            created["waiting_voice_channel_id"] = waiting.id
        if config.features.auto_create_temp_category and not temp_exists:
            category = await self._create_category_with_fallback(
                guild,
                name=config.resource_names.temp_voice_category,
                fallback_name=fallback_names.temp_voice_category,
                reason="Highlight Manager setup",
            )
            updates["temp_voice_category_id"] = category.id
            created["temp_voice_category_id"] = category.id
        if updates:
            updates["setup_created_resources"] = created
            config = await self.update(guild.id, updates)
        return config

    def validate_play_channel(
        self,
        channel: discord.abc.GuildChannel,
        config: GuildConfig,
        match_type: MatchType,
    ) -> None:
        allowed_channel_id = (
            config.apostado_play_channel_id
            if match_type == MatchType.APOSTADO
            else config.highlight_play_channel_id
        )
        if not allowed_channel_id:
            raise ConfigurationError(
                f"{match_type.label} play channel is not configured. Run /setup or /config first."
            )
        if channel.id == allowed_channel_id:
            return
        allowed_channel = self.resolve_configured_channel(
            channel.guild,
            allowed_channel_id,
            resource_key=(
                "apostado_play_channel_id"
                if match_type == MatchType.APOSTADO
                else "highlight_play_channel_id"
            ),
            expected_types=discord.abc.GuildChannel,
        )
        if allowed_channel is not None and hasattr(allowed_channel, "mention"):
            raise UserFacingError(f"You can only use this command in {allowed_channel.mention}.")
        raise UserFacingError("Use match commands only in the configured play room.")

    async def ensure_season_reward_role(
        self,
        guild: discord.Guild,
        config: GuildConfig,
        *,
        create_missing: bool,
    ) -> tuple[GuildConfig, discord.Role | None, bool]:
        role = self.resolve_configured_role(
            guild,
            config.season_reward_role_id,
            resource_key="season_reward_role_id",
        )
        created = False
        if role is None and create_missing and config.features.auto_create_season_reward_role:
            role = await guild.create_role(
                name=config.season_reward_role_name,
                reason="Highlight Manager season reward role",
            )
            created = True

        if role and (
            config.season_reward_role_id != role.id
            or config.season_reward_role_name != role.name
        ):
            config = await self.update(
                guild.id,
                {
                    "season_reward_role_id": role.id,
                    "season_reward_role_name": role.name,
                },
            )
        return config, role, created

    async def ensure_mvp_reward_role(
        self,
        guild: discord.Guild,
        config: GuildConfig,
        *,
        create_missing: bool,
    ) -> tuple[GuildConfig, discord.Role | None, bool]:
        role = self.resolve_configured_role(
            guild,
            config.mvp_reward_role_id,
            resource_key="mvp_reward_role_id",
        )
        created = False
        if role is None and create_missing and config.features.auto_create_mvp_reward_role:
            role = await guild.create_role(
                name=config.mvp_reward_role_name,
                permissions=discord.Permissions(
                    move_members=True,
                    mute_members=True,
                    deafen_members=True,
                ),
                colour=discord.Colour.gold(),
                reason="Highlight Manager MVP achievement role",
            )
            created = True
        elif role is not None:
            desired_permissions = discord.Permissions(
                move_members=True,
                mute_members=True,
                deafen_members=True,
            )
            desired_colour = discord.Colour.gold()
            if role.permissions != desired_permissions or role.colour != desired_colour:
                try:
                    role = await role.edit(
                        permissions=desired_permissions,
                        colour=desired_colour,
                        reason="Highlight Manager MVP achievement role sync",
                    )
                except discord.HTTPException as exc:
                    self.logger.warning(
                        "mvp_reward_role_sync_failed",
                        guild_id=guild.id,
                        role_id=role.id,
                        error=str(exc),
                    )

        if role and (
            config.mvp_reward_role_id != role.id
            or config.mvp_reward_role_name != role.name
        ):
            config = await self.update(
                guild.id,
                {
                    "mvp_reward_role_id": role.id,
                    "mvp_reward_role_name": role.name,
                },
            )
        return config, role, created

    async def run_setup(
        self,
        guild: discord.Guild,
        *,
        prefix: str | None = None,
        apostado_play_channel: discord.TextChannel | None = None,
        highlight_play_channel: discord.TextChannel | None = None,
        waiting_voice: discord.VoiceChannel | None = None,
        temp_voice_category: discord.CategoryChannel | None = None,
        result_category: discord.CategoryChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        admin_role: discord.Role | None = None,
        staff_role: discord.Role | None = None,
        mvp_reward_role: discord.Role | None = None,
        mvp_reward_role_name: str | None = None,
        season_reward_role: discord.Role | None = None,
        season_reward_role_name: str | None = None,
        ping_here_on_match_create: bool | None = None,
        ping_here_on_match_ready: bool | None = None,
        private_match_key_required: bool | None = None,
        create_missing: bool = False,
        result_behavior: str | None = None,
    ) -> tuple[GuildConfig, list[str]]:
        config = await self.get_or_create(guild.id)
        created_resources: list[str] = []
        created_ids = dict(config.setup_created_resources)
        fallback_names = fallback_resource_names()
        apostado_exists = (
            self.resolve_configured_channel(
                guild,
                config.apostado_play_channel_id,
                resource_key="apostado_play_channel_id",
                expected_types=discord.TextChannel,
            )
            is not None
        )
        highlight_exists = (
            self.resolve_configured_channel(
                guild,
                config.highlight_play_channel_id,
                resource_key="highlight_play_channel_id",
                expected_types=discord.TextChannel,
            )
            is not None
        )
        waiting_exists = (
            self.resolve_configured_channel(
                guild,
                config.waiting_voice_channel_id,
                resource_key="waiting_voice_channel_id",
                expected_types=discord.VoiceChannel,
            )
            is not None
        )
        temp_exists = (
            self.resolve_configured_channel(
                guild,
                config.temp_voice_category_id,
                resource_key="temp_voice_category_id",
                expected_types=discord.CategoryChannel,
            )
            is not None
        )
        result_exists = (
            self.resolve_configured_channel(
                guild,
                config.result_category_id,
                resource_key="result_category_id",
                expected_types=discord.CategoryChannel,
            )
            is not None
        )
        log_exists = (
            self.resolve_configured_channel(
                guild,
                config.log_channel_id,
                resource_key="log_channel_id",
                expected_types=discord.TextChannel,
            )
            is not None
        )

        if create_missing and apostado_play_channel is None and not apostado_exists:
            apostado_play_channel = await self._create_text_channel_with_fallback(
                guild,
                name=config.resource_names.apostado_play_channel,
                fallback_name=fallback_names.apostado_play_channel,
                reason="Highlight Manager setup",
            )
            created_resources.append(f"Created Apostado play room: {apostado_play_channel.mention}")
            created_ids["apostado_play_channel_id"] = apostado_play_channel.id
        if create_missing and highlight_play_channel is None and not highlight_exists:
            highlight_play_channel = await self._create_text_channel_with_fallback(
                guild,
                name=config.resource_names.highlight_play_channel,
                fallback_name=fallback_names.highlight_play_channel,
                reason="Highlight Manager setup",
            )
            created_resources.append(f"Created Highlight play room: {highlight_play_channel.mention}")
            created_ids["highlight_play_channel_id"] = highlight_play_channel.id
        if create_missing and waiting_voice is None and not waiting_exists:
            waiting_voice = await self._create_voice_channel_with_fallback(
                guild,
                name=config.resource_names.waiting_voice,
                fallback_name=fallback_names.waiting_voice,
                reason="Highlight Manager setup",
            )
            created_resources.append(f"Created waiting voice: {waiting_voice.mention}")
            created_ids["waiting_voice_channel_id"] = waiting_voice.id
        if create_missing and temp_voice_category is None and not temp_exists:
            temp_voice_category = await self._create_category_with_fallback(
                guild,
                name=config.resource_names.temp_voice_category,
                fallback_name=fallback_names.temp_voice_category,
                reason="Highlight Manager setup",
            )
            created_resources.append(f"Created temp voice category: **{temp_voice_category.name}**")
            created_ids["temp_voice_category_id"] = temp_voice_category.id
        if create_missing and result_category is None and not result_exists:
            result_category = await self._create_category_with_fallback(
                guild,
                name=config.resource_names.result_category,
                fallback_name=fallback_names.result_category,
                reason="Highlight Manager setup",
            )
            created_resources.append(f"Created results category: **{result_category.name}**")
            created_ids["result_category_id"] = result_category.id
        if create_missing and log_channel is None and not log_exists:
            log_channel = await self._create_text_channel_with_fallback(
                guild,
                name=config.resource_names.log_channel,
                fallback_name=fallback_names.log_channel,
                reason="Highlight Manager setup",
            )
            created_resources.append(f"Created log channel: {log_channel.mention}")
            created_ids["log_channel_id"] = log_channel.id

        updates: dict[str, Any] = {
            "prefix": prefix or config.prefix,
            "apostado_play_channel_id": (
                apostado_play_channel.id if apostado_play_channel else config.apostado_play_channel_id
            ),
            "highlight_play_channel_id": (
                highlight_play_channel.id if highlight_play_channel else config.highlight_play_channel_id
            ),
            "waiting_voice_channel_id": waiting_voice.id if waiting_voice else config.waiting_voice_channel_id,
            "temp_voice_category_id": (
                temp_voice_category.id if temp_voice_category else config.temp_voice_category_id
            ),
            "result_category_id": result_category.id if result_category else config.result_category_id,
            "log_channel_id": log_channel.id if log_channel else config.log_channel_id,
            "admin_role_ids": [admin_role.id] if admin_role else config.admin_role_ids,
            "staff_role_ids": [staff_role.id] if staff_role else config.staff_role_ids,
            "mvp_reward_role_id": (
                mvp_reward_role.id if mvp_reward_role else config.mvp_reward_role_id
            ),
            "mvp_reward_role_name": (
                mvp_reward_role_name
                or (mvp_reward_role.name if mvp_reward_role else config.mvp_reward_role_name)
            ),
            "season_reward_role_id": (
                season_reward_role.id if season_reward_role else config.season_reward_role_id
            ),
            "season_reward_role_name": (
                season_reward_role_name
                or (season_reward_role.name if season_reward_role else config.season_reward_role_name)
            ),
            "ping_here_on_match_create": (
                ping_here_on_match_create
                if ping_here_on_match_create is not None
                else config.ping_here_on_match_create
            ),
            "ping_here_on_match_ready": (
                ping_here_on_match_ready
                if ping_here_on_match_ready is not None
                else config.ping_here_on_match_ready
            ),
            "private_match_key_required": (
                private_match_key_required
                if private_match_key_required is not None
                else config.private_match_key_required
            ),
            "setup_created_resources": created_ids,
        }
        if result_behavior:
            updates["result_channel_behavior"] = result_behavior

        return await self.update(guild.id, updates), created_resources

    async def validate_ready_for_matches(self, guild: discord.Guild | int) -> GuildConfig:
        guild_id = guild.id if isinstance(guild, discord.Guild) else guild
        config = await self.get_or_create(guild_id)
        missing = []
        if not config.apostado_play_channel_id:
            missing.append("Apostado play room")
        elif isinstance(guild, discord.Guild) and self.resolve_configured_channel(
            guild,
            config.apostado_play_channel_id,
            resource_key="apostado_play_channel_id",
            expected_types=discord.TextChannel,
        ) is None:
            missing.append("Apostado play room (configured channel no longer exists)")
        if not config.highlight_play_channel_id:
            missing.append("Highlight play room")
        elif isinstance(guild, discord.Guild) and self.resolve_configured_channel(
            guild,
            config.highlight_play_channel_id,
            resource_key="highlight_play_channel_id",
            expected_types=discord.TextChannel,
        ) is None:
            missing.append("Highlight play room (configured channel no longer exists)")
        if not config.waiting_voice_channel_id:
            missing.append("Waiting Voice channel")
        elif isinstance(guild, discord.Guild) and self.resolve_configured_channel(
            guild,
            config.waiting_voice_channel_id,
            resource_key="waiting_voice_channel_id",
            expected_types=discord.VoiceChannel,
        ) is None:
            missing.append("Waiting Voice channel (configured channel no longer exists)")
        if not config.temp_voice_category_id:
            missing.append("Temporary voice category")
        elif isinstance(guild, discord.Guild) and self.resolve_configured_channel(
            guild,
            config.temp_voice_category_id,
            resource_key="temp_voice_category_id",
            expected_types=discord.CategoryChannel,
        ) is None:
            missing.append("Temporary voice category (configured category no longer exists)")
        if missing:
            raise ConfigurationError(
                "Missing required setup: " + ", ".join(missing) + ". Run /setup or /config first."
            )
        return config

    async def _create_text_channel_with_fallback(
        self,
        guild: discord.Guild,
        *,
        name: str,
        fallback_name: str,
        reason: str,
    ) -> discord.TextChannel:
        try:
            return await guild.create_text_channel(name, reason=reason)
        except discord.HTTPException as exc:
            if exc.status != 400 or name.casefold() == fallback_name.casefold():
                raise
            self.logger.warning(
                "resource_name_fallback_used",
                guild_id=guild.id,
                resource_type="text_channel",
                preferred_name=name,
                fallback_name=fallback_name,
                error=str(exc),
            )
        return await guild.create_text_channel(fallback_name, reason=reason)

    async def _create_voice_channel_with_fallback(
        self,
        guild: discord.Guild,
        *,
        name: str,
        fallback_name: str,
        reason: str,
    ) -> discord.VoiceChannel:
        try:
            return await guild.create_voice_channel(name, reason=reason)
        except discord.HTTPException as exc:
            if exc.status != 400 or name.casefold() == fallback_name.casefold():
                raise
            self.logger.warning(
                "resource_name_fallback_used",
                guild_id=guild.id,
                resource_type="voice_channel",
                preferred_name=name,
                fallback_name=fallback_name,
                error=str(exc),
            )
        return await guild.create_voice_channel(fallback_name, reason=reason)

    async def _create_category_with_fallback(
        self,
        guild: discord.Guild,
        *,
        name: str,
        fallback_name: str,
        reason: str,
    ) -> discord.CategoryChannel:
        try:
            return await guild.create_category(name, reason=reason)
        except discord.HTTPException as exc:
            if exc.status != 400 or name.casefold() == fallback_name.casefold():
                raise
            self.logger.warning(
                "resource_name_fallback_used",
                guild_id=guild.id,
                resource_type="category",
                preferred_name=name,
                fallback_name=fallback_name,
                error=str(exc),
            )
        return await guild.create_category(fallback_name, reason=reason)
