from __future__ import annotations

from dataclasses import dataclass

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.common import BootstrapSummary
from highlight_manager.models.guild_config import GuildConfig
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


class SetupService:
    APOSTADO_PLAY_CHANNEL_NAME = "apostado-play"
    HIGHLIGHT_PLAY_CHANNEL_NAME = "highlight-play"
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

        waiting_voice, created = await self._ensure_voice_channel(
            guild,
            configured_id=config.waiting_voice_channel_id,
            name="Waiting Voice",
            reason="Highlight Manager automatic setup",
        )
        created_resources.append(f"Waiting Voice: {waiting_voice.mention}") if created else reused_resources.append(f"Waiting Voice: {waiting_voice.mention}")
        setup_resource_ids["waiting_voice_channel_id"] = waiting_voice.id

        apostado_channel, created = await self._ensure_text_channel(
            guild,
            configured_id=config.apostado_channel_id,
            name=self.APOSTADO_PLAY_CHANNEL_NAME,
            reason="Highlight Manager automatic setup",
        )
        created_resources.append(f"Apostado Play Room: {apostado_channel.mention}") if created else reused_resources.append(f"Apostado Play Room: {apostado_channel.mention}")
        setup_resource_ids["apostado_channel_id"] = apostado_channel.id

        highlight_channel, created = await self._ensure_text_channel(
            guild,
            configured_id=config.highlight_channel_id,
            name=self.HIGHLIGHT_PLAY_CHANNEL_NAME,
            reason="Highlight Manager automatic setup",
        )
        created_resources.append(f"Highlight Play Room: {highlight_channel.mention}") if created else reused_resources.append(f"Highlight Play Room: {highlight_channel.mention}")
        setup_resource_ids["highlight_channel_id"] = highlight_channel.id

        temp_category, created = await self._ensure_category(
            guild,
            configured_id=config.temp_voice_category_id,
            name="Highlight Match Voices",
            reason="Highlight Manager automatic setup",
        )
        created_resources.append(f"Temp Match Category: **{temp_category.name}**") if created else reused_resources.append(f"Temp Match Category: **{temp_category.name}**")
        setup_resource_ids["temp_voice_category_id"] = temp_category.id

        result_category, created = await self._ensure_category(
            guild,
            configured_id=config.result_category_id,
            name="Match Results",
            reason="Highlight Manager automatic setup",
        )
        created_resources.append(f"Results Category: **{result_category.name}**") if created else reused_resources.append(f"Results Category: **{result_category.name}**")
        setup_resource_ids["result_category_id"] = result_category.id

        log_channel, created = await self._ensure_text_channel(
            guild,
            configured_id=config.log_channel_id,
            name="highlight-logs",
            reason="Highlight Manager automatic setup",
        )
        created_resources.append(f"Logs Channel: {log_channel.mention}") if created else reused_resources.append(f"Logs Channel: {log_channel.mention}")
        setup_resource_ids["log_channel_id"] = log_channel.id

        rank_role_map = dict(config.rank_role_map)
        rank0_role, created = await self._ensure_role(guild, 0, rank_role_map.get("0"))
        rank_role_map["0"] = rank0_role.id
        setup_resource_ids["rank_role_0"] = rank0_role.id
        label = f"Rank 0 Override Role: {rank0_role.mention}"
        created_resources.append(label) if created else reused_resources.append(label)

        updates = {
            "prefix": prefix or config.prefix,
            "apostado_channel_id": apostado_channel.id,
            "highlight_channel_id": highlight_channel.id,
            "waiting_voice_channel_id": waiting_voice.id,
            "temp_voice_category_id": temp_category.id,
            "result_category_id": result_category.id,
            "log_channel_id": log_channel.id,
            "rank_role_map": rank_role_map,
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
        reason: str,
    ) -> tuple[discord.VoiceChannel, bool]:
        channel = guild.get_channel(configured_id) if configured_id else None
        if isinstance(channel, discord.VoiceChannel):
            return channel, False
        existing = discord.utils.find(lambda item: isinstance(item, discord.VoiceChannel) and item.name.lower() == name.lower(), guild.channels)
        if isinstance(existing, discord.VoiceChannel):
            return existing, False
        return await guild.create_voice_channel(name, reason=reason), True

    async def _ensure_text_channel(
        self,
        guild: discord.Guild,
        *,
        configured_id: int | None,
        name: str,
        reason: str,
    ) -> tuple[discord.TextChannel, bool]:
        channel = guild.get_channel(configured_id) if configured_id else None
        if isinstance(channel, discord.TextChannel):
            return channel, False
        existing = discord.utils.find(lambda item: isinstance(item, discord.TextChannel) and item.name.lower() == name.lower(), guild.channels)
        if isinstance(existing, discord.TextChannel):
            return existing, False
        return await guild.create_text_channel(name, reason=reason), True

    async def _ensure_category(
        self,
        guild: discord.Guild,
        *,
        configured_id: int | None,
        name: str,
        reason: str,
    ) -> tuple[discord.CategoryChannel, bool]:
        channel = guild.get_channel(configured_id) if configured_id else None
        if isinstance(channel, discord.CategoryChannel):
            return channel, False
        existing = discord.utils.find(lambda item: isinstance(item, discord.CategoryChannel) and item.name.lower() == name.lower(), guild.channels)
        if isinstance(existing, discord.CategoryChannel):
            return existing, False
        return await guild.create_category(name, reason=reason), True

    async def _ensure_role(
        self,
        guild: discord.Guild,
        rank: int,
        configured_id: int | None,
    ) -> tuple[discord.Role, bool]:
        role = guild.get_role(configured_id) if configured_id else None
        role_name = f"Rank {rank}"
        if role:
            return role, False
        existing = discord.utils.find(lambda item: item.name.lower() == role_name.lower(), guild.roles)
        if existing:
            return existing, False
        return await guild.create_role(name=role_name, reason="Highlight Manager automatic setup"), True
