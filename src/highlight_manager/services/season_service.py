from __future__ import annotations

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.season import SeasonRecord
from highlight_manager.repositories.season_repository import SeasonRepository
from highlight_manager.services.config_service import ConfigService
from highlight_manager.services.profile_service import ProfileService


class SeasonService:
    def __init__(
        self,
        repository: SeasonRepository,
        profile_service: ProfileService,
        config_service: ConfigService,
    ) -> None:
        self.repository = repository
        self.profile_service = profile_service
        self.config_service = config_service
        self.logger = get_logger(__name__)

    async def get_active(self, guild_id: int) -> SeasonRecord | None:
        return await self.repository.get_active(guild_id)

    async def ensure_active(self, guild_id: int) -> SeasonRecord:
        current = await self.repository.get_active(guild_id)
        if current:
            return current
        latest = await self.repository.get_latest(guild_id)
        season = SeasonRecord(
            guild_id=guild_id,
            season_number=(latest.season_number + 1) if latest else 1,
            name=f"Season {(latest.season_number + 1) if latest else 1}",
        )
        await self.repository.create(season)
        self.logger.info("season_created", guild_id=guild_id, season_number=season.season_number)
        return season

    async def start_new_season(
        self,
        guild: discord.Guild,
        config: GuildConfig,
        *,
        name: str | None = None,
    ) -> SeasonRecord:
        await self.finalize_active_season(guild, config)
        latest = await self.repository.get_latest(guild.id)
        next_number = (latest.season_number + 1) if latest else 1
        season = SeasonRecord(
            guild_id=guild.id,
            season_number=next_number,
            name=name or f"Season {next_number}",
        )
        await self.repository.create(season)
        await self.profile_service.reset_for_new_season(guild, config)
        self.logger.info("season_started", guild_id=guild.id, season_number=season.season_number)
        return season

    async def end_active(self, guild: discord.Guild, config: GuildConfig) -> SeasonRecord | None:
        season = await self.finalize_active_season(guild, config)
        if season:
            self.logger.info("season_ended", guild_id=guild.id, season_number=season.season_number)
        return season

    async def finalize_active_season(
        self,
        guild: discord.Guild,
        config: GuildConfig,
    ) -> SeasonRecord | None:
        active = await self.repository.get_active(guild.id)
        if active is None:
            return None
        top_profiles = await self.profile_service.list_leaderboard(guild.id, limit=5)
        top_player_ids = [profile.user_id for profile in top_profiles]
        await self._sync_season_reward_role(guild, config, top_player_ids)
        ended = await self.repository.end_active(
            guild.id,
            ended_at=discord.utils.utcnow(),
            updates={"top_player_ids": top_player_ids},
        )
        return ended

    async def _sync_season_reward_role(
        self,
        guild: discord.Guild,
        config: GuildConfig,
        top_player_ids: list[int],
    ) -> None:
        config, role, _ = await self.config_service.ensure_season_reward_role(
            guild,
            config,
            create_missing=True,
        )
        if role is None:
            self.logger.warning("season_reward_role_unavailable", guild_id=guild.id)
            return

        target_ids = set(top_player_ids)
        for member in guild.members:
            if member.bot:
                continue
            has_role = role in member.roles
            should_have_role = member.id in target_ids
            try:
                if should_have_role and not has_role:
                    await member.add_roles(role, reason="Season top 5 reward")
                elif has_role and not should_have_role:
                    await member.remove_roles(role, reason="Season top 5 reward recalculation")
            except discord.Forbidden:
                self.logger.warning(
                    "season_reward_role_sync_forbidden",
                    guild_id=guild.id,
                    user_id=member.id,
                    role_id=role.id,
                )
            except discord.HTTPException as exc:
                self.logger.warning(
                    "season_reward_role_sync_failed",
                    guild_id=guild.id,
                    user_id=member.id,
                    role_id=role.id,
                    error=str(exc),
                )
