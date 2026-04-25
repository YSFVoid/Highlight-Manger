from __future__ import annotations

import pytest

from highlight_manager.db.models.competitive import RankTierModel, SeasonPlayerModel
from highlight_manager.modules.common.enums import RulesetKey
from highlight_manager.modules.ranks.service import RankService


class FakeRankRepository:
    def __init__(self) -> None:
        self.history: list[dict[str, object]] = []

    async def create_rating_history(self, season_player_id: int, **kwargs) -> None:
        self.history.append({"season_player_id": season_player_id, **kwargs})


def _season_players() -> list[SeasonPlayerModel]:
    return [
        SeasonPlayerModel(
            id=player_id,
            season_id=1,
            player_id=player_id,
            seed_rating=1000,
            rating=1000,
            wins=0,
            losses=0,
            matches_played=0,
            streak=0,
            peak_rating=1000,
        )
        for player_id in range(1, 5)
    ]


def _tiers() -> list[RankTierModel]:
    return [
        RankTierModel(
            id=1,
            guild_id=1,
            code="gold",
            name="Gold",
            min_rating=800,
            max_rating=None,
            sort_order=1,
            accent_hex="#D8A93B",
        )
    ]


@pytest.mark.asyncio
async def test_mvp_rating_weighting_matches_launch_fairness_rules() -> None:
    service = RankService()
    repository = FakeRankRepository()

    result = await service.apply_match_result(
        repository,  # type: ignore[arg-type]
        season_players=_season_players(),
        tiers=_tiers(),
        match_id="match-1",
        winner_player_ids={1, 2},
        ruleset_key=RulesetKey.APOSTADO,
        winner_mvp_player_id=1,
        loser_mvp_player_id=3,
    )

    assert result.changes[1].delta > result.changes[2].delta
    assert result.changes[3].delta > result.changes[4].delta
    assert result.changes[1].delta > 0
    assert result.changes[2].delta > 0
    assert result.changes[3].delta < 0
    assert result.changes[4].delta < 0
    assert len(repository.history) == 4


@pytest.mark.asyncio
async def test_highlight_rating_weight_is_stronger_than_apostado() -> None:
    service = RankService()

    apostado = await service.apply_match_result(
        FakeRankRepository(),  # type: ignore[arg-type]
        season_players=_season_players(),
        tiers=_tiers(),
        match_id="match-apostado",
        winner_player_ids={1, 2},
        ruleset_key=RulesetKey.APOSTADO,
    )
    highlight = await service.apply_match_result(
        FakeRankRepository(),  # type: ignore[arg-type]
        season_players=_season_players(),
        tiers=_tiers(),
        match_id="match-highlight",
        winner_player_ids={1, 2},
        ruleset_key=RulesetKey.HIGHLIGHT,
    )

    assert highlight.changes[1].delta > apostado.changes[1].delta
    assert highlight.changes[2].delta > apostado.changes[2].delta
    assert abs(highlight.changes[3].delta) > abs(apostado.changes[3].delta)
    assert abs(highlight.changes[4].delta) > abs(apostado.changes[4].delta)
