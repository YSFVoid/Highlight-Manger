from __future__ import annotations

from dataclasses import dataclass

from highlight_manager.db.models.competitive import RankTierModel, SeasonPlayerModel
from highlight_manager.modules.common.cache import SimpleTTLCache
from highlight_manager.modules.common.enums import RatingReason
from highlight_manager.modules.ranks.calculator import DEFAULT_TIERS, RatingChange, bounded_rating, calculate_delta
from highlight_manager.modules.ranks.repository import RankRepository


@dataclass(slots=True)
class RankedMatchResult:
    changes: dict[int, RatingChange]


class RankService:
    def __init__(self) -> None:
        self._tier_cache = SimpleTTLCache(maxsize=128, ttl=300)

    async def ensure_default_tiers(self, repository: RankRepository, guild_id: int) -> list[RankTierModel]:
        cached = self._tier_cache.get(str(guild_id))
        if isinstance(cached, list) and cached:
            return cached
        tiers = await repository.list_tiers(guild_id)
        if tiers:
            self._tier_cache.set(str(guild_id), tiers)
            return tiers
        created: list[RankTierModel] = []
        for index, tier in enumerate(DEFAULT_TIERS, start=1):
            created.append(
                await repository.create_tier(
                    guild_id,
                    code=tier.code,
                    name=tier.name,
                    min_rating=tier.min_rating,
                    max_rating=tier.max_rating,
                    sort_order=index,
                    accent_hex=tier.accent_hex,
                )
            )
        self._tier_cache.set(str(guild_id), created)
        return created

    def resolve_tier(self, tiers: list[RankTierModel], rating: int) -> RankTierModel | None:
        for tier in tiers:
            max_ok = tier.max_rating is None or rating <= tier.max_rating
            if rating >= tier.min_rating and max_ok:
                return tier
        return tiers[-1] if tiers else None

    async def apply_match_result(
        self,
        repository: RankRepository,
        *,
        season_players: list[SeasonPlayerModel],
        tiers: list[RankTierModel],
        match_id,
        winner_player_ids: set[int],
        actor_player_id: int | None = None,
    ) -> RankedMatchResult:
        team_one = [row for row in season_players if row.player_id in winner_player_ids]
        team_two = [row for row in season_players if row.player_id not in winner_player_ids]
        if not team_one or not team_two:
            raise ValueError("Both teams must contain at least one player.")

        team_one_rating = sum(row.rating for row in team_one) / len(team_one)
        team_two_rating = sum(row.rating for row in team_two) / len(team_two)
        changes: dict[int, RatingChange] = {}

        for row in team_one:
            before = row.rating
            delta = calculate_delta(
                rating=row.rating,
                matches_played=row.matches_played,
                team_rating=team_one_rating,
                opponent_rating=team_two_rating,
                actual=1.0,
            )
            after = bounded_rating(before, delta)
            row.rating = after
            row.matches_played += 1
            row.wins += 1
            row.streak = max(1, row.streak + 1)
            row.peak_rating = max(row.peak_rating, after)
            tier = self.resolve_tier(tiers, after)
            row.current_tier_id = tier.id if tier else None
            changes[row.player_id] = RatingChange(row.player_id, before, after, after - before)
            await repository.create_rating_history(
                row.id,
                match_id=match_id,
                before_rating=before,
                after_rating=after,
                delta=after - before,
                reason=RatingReason.MATCH_RESULT,
                actor_player_id=actor_player_id,
            )

        for row in team_two:
            before = row.rating
            delta = calculate_delta(
                rating=row.rating,
                matches_played=row.matches_played,
                team_rating=team_two_rating,
                opponent_rating=team_one_rating,
                actual=0.0,
            )
            after = bounded_rating(before, delta)
            row.rating = after
            row.matches_played += 1
            row.losses += 1
            row.streak = min(-1, row.streak - 1) if row.streak <= 0 else -1
            row.peak_rating = max(row.peak_rating, after)
            tier = self.resolve_tier(tiers, after)
            row.current_tier_id = tier.id if tier else None
            changes[row.player_id] = RatingChange(row.player_id, before, after, after - before)
            await repository.create_rating_history(
                row.id,
                match_id=match_id,
                before_rating=before,
                after_rating=after,
                delta=after - before,
                reason=RatingReason.MATCH_RESULT,
                actor_player_id=actor_player_id,
            )
        return RankedMatchResult(changes=changes)
