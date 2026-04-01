from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.competitive import SeasonModel, SeasonPlayerModel
from highlight_manager.modules.common.enums import SeasonStatus


class SeasonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, guild_id: int) -> SeasonModel | None:
        return await self.session.scalar(
            select(SeasonModel).where(
                SeasonModel.guild_id == guild_id,
                SeasonModel.status == SeasonStatus.ACTIVE,
            )
        )

    async def get_latest_number(self, guild_id: int) -> int:
        value = await self.session.scalar(
            select(func.max(SeasonModel.season_number)).where(SeasonModel.guild_id == guild_id)
        )
        return int(value or 0)

    async def create(self, guild_id: int, *, name: str, season_number: int) -> SeasonModel:
        season = SeasonModel(guild_id=guild_id, name=name, season_number=season_number)
        self.session.add(season)
        await self.session.flush()
        return season

    async def end_active(self, guild_id: int) -> SeasonModel | None:
        season = await self.get_active(guild_id)
        if season is None:
            return None
        season.status = SeasonStatus.ENDED
        return season

    async def ensure_season_player(
        self,
        season_id: int,
        player_id: int,
        *,
        seed_rating: int,
        legacy_points: int | None = None,
        legacy_rank: int | None = None,
    ) -> SeasonPlayerModel:
        season_player = await self.session.scalar(
            select(SeasonPlayerModel).where(
                SeasonPlayerModel.season_id == season_id,
                SeasonPlayerModel.player_id == player_id,
            )
        )
        if season_player is None:
            season_player = SeasonPlayerModel(
                season_id=season_id,
                player_id=player_id,
                seed_rating=seed_rating,
                rating=seed_rating,
                peak_rating=seed_rating,
                legacy_points=legacy_points,
                legacy_rank=legacy_rank,
            )
            self.session.add(season_player)
            await self.session.flush()
        return season_player

    async def get_season_players(self, season_id: int, player_ids: list[int]) -> list[SeasonPlayerModel]:
        result = await self.session.scalars(
            select(SeasonPlayerModel).where(
                SeasonPlayerModel.season_id == season_id,
                SeasonPlayerModel.player_id.in_(player_ids),
            )
        )
        return list(result.all())
