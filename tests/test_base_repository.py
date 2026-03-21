from datetime import UTC, datetime

from highlight_manager.models.match import MatchRecord
from highlight_manager.repositories.base import BaseRepository


def test_base_repository_normalizes_naive_mongo_datetimes_to_utc() -> None:
    repository = BaseRepository(collection=None, model_type=MatchRecord)

    match = repository._to_model(
        {
            "guild_id": 1,
            "match_number": 10,
            "creator_id": 99,
            "mode": "1v1",
            "match_type": "apostado",
            "status": "OPEN",
            "team1_player_ids": [99],
            "team2_player_ids": [],
            "created_at": datetime(2026, 3, 21, 19, 54, 0),
            "queue_opened_at": datetime(2026, 3, 21, 19, 54, 0),
            "queue_expires_at": datetime(2026, 3, 21, 19, 59, 0),
        }
    )

    assert match is not None
    assert match.created_at.tzinfo == UTC
    assert match.queue_opened_at is not None
    assert match.queue_opened_at.tzinfo == UTC
    assert match.queue_expires_at is not None
    assert match.queue_expires_at.tzinfo == UTC
    assert int(match.queue_expires_at.timestamp() - match.queue_opened_at.timestamp()) == 300
