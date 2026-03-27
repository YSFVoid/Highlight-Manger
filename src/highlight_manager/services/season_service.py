from __future__ import annotations

import discord

from highlight_manager.config.logging import get_logger
from highlight_manager.models.season import SeasonRecord
from highlight_manager.repositories.season_repository import SeasonRepository
from highlight_manager.services.profile_service import ProfileService


class SeasonService:
    def __init__(self, repository: SeasonRepository, profile_service: ProfileService) -> None:
        self.repository = repository
        self.profile_service = profile_service
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
        config,
        *,
        name: str | None = None,
    ) -> SeasonRecord:
        await self.repository.end_active(guild.id, ended_at=discord.utils.utcnow())
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

    async def end_active(self, guild_id: int) -> SeasonRecord | None:
        season = await self.repository.end_active(guild_id, ended_at=discord.utils.utcnow())
        if season:
            self.logger.info("season_ended", guild_id=guild_id, season_number=season.season_number)
        return season
