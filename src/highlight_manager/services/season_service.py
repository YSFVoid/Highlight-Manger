from __future__ import annotations

from dataclasses import dataclass

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.season import SeasonRecord
from highlight_manager.repositories.season_repository import SeasonRepository
from highlight_manager.services.config_service import ConfigService
from highlight_manager.services.profile_service import ProfileService


@dataclass(slots=True)
class SeasonRewardSyncResult:
    role_id: int | None = None
    assigned_count: int = 0
    removed_count: int = 0
    failed_count: int = 0
    top_player_ids: list[int] | None = None


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
        self.logger.info(
            "season_finalize_started",
            guild_id=guild.id,
            season_number=active.season_number,
            reward_top_count=config.season_reward_top_count,
        )
        top_profiles = await self.profile_service.list_leaderboard(guild.id, limit=config.season_reward_top_count)
        top_player_ids = [profile.user_id for profile in top_profiles]
        reward_sync = await self._sync_season_reward_role(guild, config, top_player_ids)
        ended = await self.repository.end_active(
            guild.id,
            ended_at=discord.utils.utcnow(),
            updates={"top_player_ids": top_player_ids},
        )
        self.logger.info(
            "season_finalize_completed",
            guild_id=guild.id,
            season_number=active.season_number,
            top_player_ids=top_player_ids,
            db_result=ended is not None,
            reward_role_id=reward_sync.role_id,
            reward_assigned_count=reward_sync.assigned_count,
            reward_removed_count=reward_sync.removed_count,
            reward_failed_count=reward_sync.failed_count,
        )
        return ended

    async def _sync_season_reward_role(
        self,
        guild: discord.Guild,
        config: GuildConfig,
        top_player_ids: list[int],
    ) -> SeasonRewardSyncResult:
        config, role, _ = await self.config_service.ensure_season_reward_role(
            guild,
            config,
            create_missing=True,
        )
        if role is None:
            self.logger.warning("season_reward_role_unavailable", guild_id=guild.id)
            return SeasonRewardSyncResult(top_player_ids=list(top_player_ids))

        target_ids = set(top_player_ids)
        assigned_count = 0
        removed_count = 0
        failed_count = 0
        for member in guild.members:
            if member.bot:
                continue
            has_role = role in member.roles
            should_have_role = member.id in target_ids
            try:
                if should_have_role and not has_role:
                    await member.add_roles(role, reason="Highlight Manager season reward sync")
                    assigned_count += 1
                elif has_role and not should_have_role:
                    await member.remove_roles(role, reason="Highlight Manager season reward sync")
                    removed_count += 1
            except discord.Forbidden:
                failed_count += 1
                self.logger.warning(
                    "season_reward_role_sync_forbidden",
                    guild_id=guild.id,
                    user_id=member.id,
                    role_id=role.id,
                )
            except discord.HTTPException as exc:
                failed_count += 1
                self.logger.warning(
                    "season_reward_role_sync_failed",
                    guild_id=guild.id,
                    user_id=member.id,
                    role_id=role.id,
                    error=str(exc),
                )
        result = SeasonRewardSyncResult(
            role_id=role.id,
            assigned_count=assigned_count,
            removed_count=removed_count,
            failed_count=failed_count,
            top_player_ids=list(top_player_ids),
        )
        self.logger.info(
            "season_reward_role_sync_completed",
            guild_id=guild.id,
            role_id=role.id,
            top_player_ids=top_player_ids,
            assigned_count=assigned_count,
            removed_count=removed_count,
            failed_count=failed_count,
        )
        return result
