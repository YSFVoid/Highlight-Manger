from __future__ import annotations

from typing import Any

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.config.settings import Settings
from highlight_manager.models.enums import MatchType
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.repositories.config_repository import ConfigRepository
from highlight_manager.utils.exceptions import ConfigurationError
from highlight_manager.utils.permissions import member_has_any_role


class ConfigService:
    PLAY_CHANNEL_NAMES = {
        MatchType.APOSTADO: "apostado-play",
        MatchType.HIGHLIGHT: "highlight-play",
    }

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
        waiting_exists = isinstance(guild.get_channel(config.waiting_voice_channel_id), discord.VoiceChannel) if config.waiting_voice_channel_id else False
        temp_exists = isinstance(guild.get_channel(config.temp_voice_category_id), discord.CategoryChannel) if config.temp_voice_category_id else False

        if config.features.auto_create_waiting_voice and not waiting_exists:
            waiting = await guild.create_voice_channel("Waiting Voice", reason="Highlight Manager setup")
            updates["waiting_voice_channel_id"] = waiting.id
            created["waiting_voice_channel_id"] = waiting.id
        if config.features.auto_create_temp_category and not temp_exists:
            category = await guild.create_category("Highlight Match Voices", reason="Highlight Manager setup")
            updates["temp_voice_category_id"] = category.id
            created["temp_voice_category_id"] = category.id
        if updates:
            updates["setup_created_resources"] = created
            config = await self.update(guild.id, updates)
        return config

    async def run_setup(
        self,
        guild: discord.Guild,
        *,
        prefix: str | None = None,
        apostado_channel: discord.TextChannel | None = None,
        highlight_channel: discord.TextChannel | None = None,
        waiting_voice: discord.VoiceChannel | None = None,
        temp_voice_category: discord.CategoryChannel | None = None,
        result_category: discord.CategoryChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        admin_role: discord.Role | None = None,
        staff_role: discord.Role | None = None,
        rank0_role: discord.Role | None = None,
        rank1_role: discord.Role | None = None,
        rank2_role: discord.Role | None = None,
        rank3_role: discord.Role | None = None,
        rank4_role: discord.Role | None = None,
        rank5_role: discord.Role | None = None,
        create_missing: bool = False,
        result_behavior: str | None = None,
    ) -> tuple[GuildConfig, list[str]]:
        config = await self.get_or_create(guild.id)
        created_resources: list[str] = []
        created_ids = dict(config.setup_created_resources)
        waiting_exists = isinstance(guild.get_channel(config.waiting_voice_channel_id), discord.VoiceChannel) if config.waiting_voice_channel_id else False
        temp_exists = isinstance(guild.get_channel(config.temp_voice_category_id), discord.CategoryChannel) if config.temp_voice_category_id else False
        result_exists = isinstance(guild.get_channel(config.result_category_id), discord.CategoryChannel) if config.result_category_id else False
        log_exists = isinstance(guild.get_channel(config.log_channel_id), discord.TextChannel) if config.log_channel_id else False

        if create_missing and waiting_voice is None and not waiting_exists:
            waiting_voice = await guild.create_voice_channel("Waiting Voice", reason="Highlight Manager setup")
            created_resources.append(f"Created waiting voice: {waiting_voice.mention}")
            created_ids["waiting_voice_channel_id"] = waiting_voice.id
        if create_missing and temp_voice_category is None and not temp_exists:
            temp_voice_category = await guild.create_category("Highlight Match Voices", reason="Highlight Manager setup")
            created_resources.append(f"Created temp voice category: **{temp_voice_category.name}**")
            created_ids["temp_voice_category_id"] = temp_voice_category.id
        if create_missing and result_category is None and not result_exists:
            result_category = await guild.create_category("Match Results", reason="Highlight Manager setup")
            created_resources.append(f"Created results category: **{result_category.name}**")
            created_ids["result_category_id"] = result_category.id
        if create_missing and log_channel is None and not log_exists:
            log_channel = await guild.create_text_channel("highlight-logs", reason="Highlight Manager setup")
            created_resources.append(f"Created log channel: {log_channel.mention}")
            created_ids["log_channel_id"] = log_channel.id

        rank_role_map = dict(config.rank_role_map)
        if rank0_role is not None:
            rank_role_map["0"] = rank0_role.id

        updates: dict[str, Any] = {
            "prefix": prefix or config.prefix,
            "apostado_channel_id": apostado_channel.id if apostado_channel else config.apostado_channel_id,
            "highlight_channel_id": highlight_channel.id if highlight_channel else config.highlight_channel_id,
            "waiting_voice_channel_id": waiting_voice.id if waiting_voice else config.waiting_voice_channel_id,
            "temp_voice_category_id": (
                temp_voice_category.id if temp_voice_category else config.temp_voice_category_id
            ),
            "result_category_id": result_category.id if result_category else config.result_category_id,
            "log_channel_id": log_channel.id if log_channel else config.log_channel_id,
            "admin_role_ids": [admin_role.id] if admin_role else config.admin_role_ids,
            "staff_role_ids": [staff_role.id] if staff_role else config.staff_role_ids,
            "rank_role_map": rank_role_map,
            "setup_created_resources": created_ids,
        }
        if result_behavior:
            updates["result_channel_behavior"] = result_behavior

        return await self.update(guild.id, updates), created_resources

    async def validate_ready_for_matches(self, guild_id: int) -> GuildConfig:
        config = await self.get_or_create(guild_id)
        missing = []
        if not config.waiting_voice_channel_id:
            missing.append("Waiting Voice channel")
        if not config.temp_voice_category_id:
            missing.append("Temporary voice category")
        if missing:
            raise ConfigurationError(
                "Missing required setup: " + ", ".join(missing) + ". Run /setup or /config first."
            )
        return config

    async def backfill_play_channels(self, guild: discord.Guild, config: GuildConfig | None = None) -> GuildConfig:
        config = config or await self.get_or_create(guild.id)
        updates: dict[str, Any] = {}

        apostado_channel = self._resolve_named_text_channel(
            guild,
            config.apostado_channel_id,
            self.PLAY_CHANNEL_NAMES[MatchType.APOSTADO],
        )
        if apostado_channel and apostado_channel.id != config.apostado_channel_id:
            updates["apostado_channel_id"] = apostado_channel.id

        highlight_channel = self._resolve_named_text_channel(
            guild,
            config.highlight_channel_id,
            self.PLAY_CHANNEL_NAMES[MatchType.HIGHLIGHT],
        )
        if highlight_channel and highlight_channel.id != config.highlight_channel_id:
            updates["highlight_channel_id"] = highlight_channel.id

        if updates:
            config = await self.update(guild.id, updates)
        return config

    def _resolve_named_text_channel(
        self,
        guild: discord.Guild,
        configured_id: int | None,
        expected_name: str,
    ) -> discord.TextChannel | None:
        channel = guild.get_channel(configured_id) if configured_id else None
        if isinstance(channel, discord.TextChannel):
            return channel
        existing = discord.utils.find(
            lambda item: isinstance(item, discord.TextChannel) and item.name.lower() == expected_name.lower(),
            guild.channels,
        )
        return existing if isinstance(existing, discord.TextChannel) else None
