from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.competitive import RankTierModel, RatingHistoryModel, SeasonPlayerModel


class RankRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_tiers(self, guild_id: int) -> list[RankTierModel]:
        result = await self.session.scalars(
            select(RankTierModel)
            .where(RankTierModel.guild_id == guild_id)
            .order_by(RankTierModel.sort_order.asc())
        )
        return list(result.all())

    async def create_tier(
        self,
        guild_id: int,
        *,
        code: str,
        name: str,
        min_rating: int,
        max_rating: int | None,
        sort_order: int,
        accent_hex: str,
    ) -> RankTierModel:
        tier = RankTierModel(
            guild_id=guild_id,
            code=code,
            name=name,
            min_rating=min_rating,
            max_rating=max_rating,
            sort_order=sort_order,
            accent_hex=accent_hex,
        )
        self.session.add(tier)
        await self.session.flush()
        return tier

    async def list_leaderboard(self, season_id: int, *, limit: int | None = 10) -> list[SeasonPlayerModel]:
        stmt = (
            select(SeasonPlayerModel)
            .where(SeasonPlayerModel.season_id == season_id)
            .order_by(
                SeasonPlayerModel.rating.desc(),
                SeasonPlayerModel.wins.desc(),
                SeasonPlayerModel.peak_rating.desc(),
                SeasonPlayerModel.matches_played.asc(),
                SeasonPlayerModel.player_id.asc(),
            )
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def create_rating_history(
        self,
        season_player_id: int,
        *,
        match_id,
        before_rating: int,
        after_rating: int,
        delta: int,
        reason,
        actor_player_id: int | None = None,
    ) -> RatingHistoryModel:
        history = RatingHistoryModel(
            season_player_id=season_player_id,
            match_id=match_id,
            before_rating=before_rating,
            after_rating=after_rating,
            delta=delta,
            reason=reason,
            actor_player_id=actor_player_id,
        )
        self.session.add(history)
        await self.session.flush()
        return history
