from __future__ import annotations

from dataclasses import dataclass

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.common import BootstrapSummary
from highlight_manager.models.guild_config import GuildConfig, fallback_resource_names
from highlight_manager.services.bootstrap_service import BootstrapService
from highlight_manager.services.config_service import ConfigService
from highlight_manager.utils.dates import utcnow
from highlight_manager.utils.exceptions import UserFacingError


@dataclass(slots=True)
class SetupRunResult:
    config: GuildConfig
    created_resources: list[str]
    reused_resources: list[str]
    bootstrap_summary: BootstrapSummary | None
    first_bootstrap_ran: bool


@dataclass(slots=True)
class EnsuredResource:
    channel: discord.abc.GuildChannel
    created: bool
    fallback_used: bool = False


class SetupService:
    REQUIRED_SETUP_PERMISSIONS = [
        "manage_channels",
        "move_members",
        "connect",
        "view_channel",
        "send_messages",
        "read_message_history",
        "embed_links",
        "manage_roles",
        "manage_nicknames",
    ]

    def __init__(self, config_service: ConfigService, bootstrap_service: BootstrapService) -> None:
        self.config_service = config_service
        self.bootstrap_service = bootstrap_service
        self.logger = get_logger(__name__)

    def validate_permissions(self, guild: discord.Guild) -> None:
        me = guild.me
        if me is None:
            raise UserFacingError("Bot member could not be resolved in this guild.")
        missing = [permission for permission in self.REQUIRED_SETUP_PERMISSIONS if not getattr(me.guild_permissions, permission, False)]
        if missing:
            pretty = ", ".join(permission.replace("_", " ") for permission in missing)
            raise UserFacingError(f"Setup cannot continue because the bot is missing: {pretty}.")

    async def run(self, guild: discord.Guild, *, prefix: str | None, repair: bool = False) -> SetupRunResult:
        self.validate_permissions(guild)
        config = await self.config_service.get_or_create(guild.id)
        created_resources: list[str] = []
        reused_resources: list[str] = []
        setup_resource_ids = dict(config.setup_created_resources)
        fallback_names = fallback_resource_names()

        apostado_play_result = await self._ensure_text_channel(
            guild,
            configured_id=config.apostado_play_channel_id,
            name=config.resource_names.apostado_play_channel,
            fallback_name=fallback_names.apostado_play_channel,
            reason="Highlight Manager automatic setup",
        )
        apostado_play_channel = apostado_play_result.channel
        label = self._format_resource_entry(
            "Apostado Play Room",
            apostado_play_channel.mention,
            fallback_used=apostado_play_result.fallback_used,
        )
        created_resources.append(label) if apostado_play_result.created else reused_resources.append(label)
        setup_resource_ids["apostado_play_channel_id"] = apostado_play_channel.id

        highlight_play_result = await self._ensure_text_channel(
            guild,
            configured_id=config.highlight_play_channel_id,
            name=config.resource_names.highlight_play_channel,
            fallback_name=fallback_names.highlight_play_channel,
            reason="Highlight Manager automatic setup",
        )
        highlight_play_channel = highlight_play_result.channel
        label = self._format_resource_entry(
            "Highlight Play Room",
            highlight_play_channel.mention,
            fallback_used=highlight_play_result.fallback_used,
        )
        created_resources.append(label) if highlight_play_result.created else reused_resources.append(label)
        setup_resource_ids["highlight_play_channel_id"] = highlight_play_channel.id

        waiting_voice_result = await self._ensure_voice_channel(
            guild,
            configured_id=config.waiting_voice_channel_id,
            name=config.resource_names.waiting_voice,
            fallback_name=fallback_names.waiting_voice,
            reason="Highlight Manager automatic setup",
        )
        waiting_voice = waiting_voice_result.channel
        label = self._format_resource_entry(
            "Waiting Voice",
            waiting_voice.mention,
            fallback_used=waiting_voice_result.fallback_used,
        )
        created_resources.append(label) if waiting_voice_result.created else reused_resources.append(label)
        setup_resource_ids["waiting_voice_channel_id"] = waiting_voice.id

        temp_category_result = await self._ensure_category(
            guild,
            configured_id=config.temp_voice_category_id,
            name=config.resource_names.temp_voice_category,
            fallback_name=fallback_names.temp_voice_category,
            reason="Highlight Manager automatic setup",
        )
        temp_category = temp_category_result.channel
        label = self._format_resource_entry(
            "Temp Match Category",
            f"**{temp_category.name}**",
            fallback_used=temp_category_result.fallback_used,
        )
        created_resources.append(label) if temp_category_result.created else reused_resources.append(label)
        setup_resource_ids["temp_voice_category_id"] = temp_category.id

        result_category_result = await self._ensure_category(
            guild,
            configured_id=config.result_category_id,
            name=config.resource_names.result_category,
            fallback_name=fallback_names.result_category,
            reason="Highlight Manager automatic setup",
        )
        result_category = result_category_result.channel
        label = self._format_resource_entry(
            "Results Category",
            f"**{result_category.name}**",
            fallback_used=result_category_result.fallback_used,
        )
        created_resources.append(label) if result_category_result.created else reused_resources.append(label)
        setup_resource_ids["result_category_id"] = result_category.id

        log_channel_result = await self._ensure_text_channel(
            guild,
            configured_id=config.log_channel_id,
            name=config.resource_names.log_channel,
            fallback_name=fallback_names.log_channel,
            reason="Highlight Manager automatic setup",
        )
        log_channel = log_channel_result.channel
        label = self._format_resource_entry(
            "Logs Channel",
            log_channel.mention,
            fallback_used=log_channel_result.fallback_used,
        )
        created_resources.append(label) if log_channel_result.created else reused_resources.append(label)
        setup_resource_ids["log_channel_id"] = log_channel.id

        config, mvp_reward_role, created = await self.config_service.ensure_mvp_reward_role(
            guild,
            config,
            create_missing=True,
        )
        if mvp_reward_role is not None:
            setup_resource_ids["mvp_reward_role_id"] = mvp_reward_role.id
            label = f"Mvp Role: {mvp_reward_role.mention}"
            created_resources.append(label) if created else reused_resources.append(label)

        config, season_reward_role, created = await self.config_service.ensure_season_reward_role(
            guild,
            config,
            create_missing=True,
        )
        if season_reward_role is not None:
            setup_resource_ids["season_reward_role_id"] = season_reward_role.id
            label = f"Season Reward Role: {season_reward_role.mention}"
            created_resources.append(label) if created else reused_resources.append(label)

        updates = {
            "prefix": prefix or config.prefix,
            "apostado_play_channel_id": apostado_play_channel.id,
            "highlight_play_channel_id": highlight_play_channel.id,
            "waiting_voice_channel_id": waiting_voice.id,
            "temp_voice_category_id": temp_category.id,
            "result_category_id": result_category.id,
            "log_channel_id": log_channel.id,
            "mvp_reward_role_id": mvp_reward_role.id if mvp_reward_role else config.mvp_reward_role_id,
            "mvp_reward_role_name": (
                mvp_reward_role.name if mvp_reward_role else config.mvp_reward_role_name
            ),
            "season_reward_role_id": season_reward_role.id if season_reward_role else config.season_reward_role_id,
            "season_reward_role_name": (
                season_reward_role.name if season_reward_role else config.season_reward_role_name
            ),
            "setup_created_resources": setup_resource_ids,
        }
        config = await self.config_service.update(guild.id, updates)

        bootstrap_summary: BootstrapSummary | None = None
        first_bootstrap_ran = False
        if not repair and not config.bootstrap_completed and config.features.bootstrap_on_first_setup:
            bootstrap_summary = await self.bootstrap_service.run(guild, config)
            config = await self.config_service.update(
                guild.id,
                {
                    "bootstrap_completed": True,
                    "bootstrap_completed_at": utcnow(),
                    "bootstrap_last_summary": bootstrap_summary.model_dump(mode="python"),
                },
            )
            first_bootstrap_ran = True
        return SetupRunResult(
            config=config,
            created_resources=created_resources,
            reused_resources=reused_resources,
            bootstrap_summary=bootstrap_summary,
            first_bootstrap_ran=first_bootstrap_ran,
        )

    async def repair(self, guild: discord.Guild) -> SetupRunResult:
        return await self.run(guild, prefix=None, repair=True)

    async def _ensure_voice_channel(
        self,
        guild: discord.Guild,
        *,
        configured_id: int | None,
        name: str,
        fallback_name: str,
        reason: str,
    ) -> EnsuredResource:
        channel = guild.get_channel(configured_id) if configured_id else None
        if isinstance(channel, discord.VoiceChannel):
            return EnsuredResource(channel=channel, created=False)
        accepted_names = {name.casefold(), fallback_name.casefold()}
        existing = discord.utils.find(
            lambda item: isinstance(item, discord.VoiceChannel) and item.name.casefold() in accepted_names,
            guild.channels,
        )
        if isinstance(existing, discord.VoiceChannel):
            return EnsuredResource(channel=existing, created=False)
        return await self._create_voice_channel_with_fallback(guild, name=name, fallback_name=fallback_name, reason=reason)

    async def _ensure_text_channel(
        self,
        guild: discord.Guild,
        *,
        configured_id: int | None,
        name: str,
        fallback_name: str,
        reason: str,
    ) -> EnsuredResource:
        channel = guild.get_channel(configured_id) if configured_id else None
        if isinstance(channel, discord.TextChannel):
            return EnsuredResource(channel=channel, created=False)
        accepted_names = {name.casefold(), fallback_name.casefold()}
        existing = discord.utils.find(
            lambda item: isinstance(item, discord.TextChannel) and item.name.casefold() in accepted_names,
            guild.channels,
        )
        if isinstance(existing, discord.TextChannel):
            return EnsuredResource(channel=existing, created=False)
        return await self._create_text_channel_with_fallback(guild, name=name, fallback_name=fallback_name, reason=reason)

    async def _ensure_category(
        self,
        guild: discord.Guild,
        *,
        configured_id: int | None,
        name: str,
        fallback_name: str,
        reason: str,
    ) -> EnsuredResource:
        channel = guild.get_channel(configured_id) if configured_id else None
        if isinstance(channel, discord.CategoryChannel):
            return EnsuredResource(channel=channel, created=False)
        accepted_names = {name.casefold(), fallback_name.casefold()}
        existing = discord.utils.find(
            lambda item: isinstance(item, discord.CategoryChannel) and item.name.casefold() in accepted_names,
            guild.channels,
        )
        if isinstance(existing, discord.CategoryChannel):
            return EnsuredResource(channel=existing, created=False)
        return await self._create_category_with_fallback(guild, name=name, fallback_name=fallback_name, reason=reason)

    def _format_resource_entry(self, label: str, value: str, *, fallback_used: bool) -> str:
        suffix = " (fallback ASCII name used)" if fallback_used else ""
        return f"{label}: {value}{suffix}"

    async def _create_text_channel_with_fallback(
        self,
        guild: discord.Guild,
        *,
        name: str,
        fallback_name: str,
        reason: str,
    ) -> EnsuredResource:
        try:
            return EnsuredResource(
                channel=await guild.create_text_channel(name, reason=reason),
                created=True,
            )
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
        return EnsuredResource(
            channel=await guild.create_text_channel(fallback_name, reason=reason),
            created=True,
            fallback_used=True,
        )

    async def _create_voice_channel_with_fallback(
        self,
        guild: discord.Guild,
        *,
        name: str,
        fallback_name: str,
        reason: str,
    ) -> EnsuredResource:
        try:
            return EnsuredResource(
                channel=await guild.create_voice_channel(name, reason=reason),
                created=True,
            )
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
        return EnsuredResource(
            channel=await guild.create_voice_channel(fallback_name, reason=reason),
            created=True,
            fallback_used=True,
        )

    async def _create_category_with_fallback(
        self,
        guild: discord.Guild,
        *,
        name: str,
        fallback_name: str,
        reason: str,
    ) -> EnsuredResource:
        try:
            return EnsuredResource(
                channel=await guild.create_category(name, reason=reason),
                created=True,
            )
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
        return EnsuredResource(
            channel=await guild.create_category(fallback_name, reason=reason),
            created=True,
            fallback_used=True,
        )
