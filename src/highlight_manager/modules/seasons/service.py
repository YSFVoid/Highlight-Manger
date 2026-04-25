from __future__ import annotations

from highlight_manager.db.models.competitive import SeasonModel, SeasonPlayerModel
from highlight_manager.db.models.core import GuildSettingModel
from highlight_manager.modules.common.cache import SimpleTTLCache
from highlight_manager.modules.common.enums import SeasonStatus
from highlight_manager.modules.common.exceptions import NotFoundError, ValidationError
from highlight_manager.modules.seasons.repository import SeasonRepository


class SeasonService:
    def __init__(self) -> None:
        self._active_cache = SimpleTTLCache(maxsize=128, ttl=60)

    async def ensure_active(self, repository: SeasonRepository, guild_id: int, settings: GuildSettingModel) -> SeasonModel:
        cached = self._active_cache.get(str(guild_id))
        if isinstance(cached, SeasonModel):
            settings.current_season_id = cached.id
            return cached
        season = await repository.get_active(guild_id)
        if season is None:
            next_number = await repository.get_latest_number(guild_id) + 1
            season = await repository.create(guild_id, name=f"Season {next_number}", season_number=next_number)
        settings.current_season_id = season.id
        self._active_cache.set(str(guild_id), season)
        return season

    async def start_next_season(
        self,
        repository: SeasonRepository,
        guild_id: int,
        settings: GuildSettingModel,
        *,
        name: str | None = None,
    ) -> SeasonModel:
        await repository.end_active(guild_id)
        next_number = await repository.get_latest_number(guild_id) + 1
        season = await repository.create(
            guild_id,
            name=name or f"Season {next_number}",
            season_number=next_number,
        )
        settings.current_season_id = season.id
        self._active_cache.set(str(guild_id), season)
        return season

    async def ensure_player(
        self,
        repository: SeasonRepository,
        season_id: int,
        player_id: int,
        *,
        seed_rating: int = 1000,
        legacy_points: int | None = None,
        legacy_rank: int | None = None,
    ) -> SeasonPlayerModel:
        return await repository.ensure_season_player(
            season_id,
            player_id,
            seed_rating=seed_rating,
            legacy_points=legacy_points,
            legacy_rank=legacy_rank,
        )

    async def list_history(
        self,
        repository: SeasonRepository,
        guild_id: int,
        *,
        limit: int | None = 8,
    ) -> list[SeasonModel]:
        return await repository.list_seasons(guild_id, limit=limit)

    async def resolve_archived_season(
        self,
        repository: SeasonRepository,
        guild_id: int,
        season_number: int,
    ) -> SeasonModel:
        season = await repository.get_by_number(guild_id, season_number)
        if season is None:
            raise NotFoundError(f"Season {season_number} was not found.")
        if season.status == SeasonStatus.ACTIVE:
            raise ValidationError(
                f"Season {season_number} is still active. Use the command without a season number for the live view."
            )
        return season
