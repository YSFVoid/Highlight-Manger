from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from highlight_manager.db.models.competitive import MatchModel, MatchPlayerModel, QueueModel, QueuePlayerModel
from highlight_manager.modules.common.enums import MatchMode, MatchState, QueueState, RulesetKey
from highlight_manager.modules.matches.types import MatchSnapshot, QueueSnapshot
from highlight_manager.modules.matches.ui import build_match_embed, build_queue_embed


def test_queue_embed_highlights_required_room_setup() -> None:
    queue = QueueModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        creator_player_id=1,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.TWO_V_TWO,
        state=QueueState.FULL_PENDING_ROOM_INFO,
        team_size=2,
        room_info_deadline_at=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    players = [
        QueuePlayerModel(queue_id=queue.id, player_id=1, team_number=1),
        QueuePlayerModel(queue_id=queue.id, player_id=2, team_number=1),
        QueuePlayerModel(queue_id=queue.id, player_id=3, team_number=2),
        QueuePlayerModel(queue_id=queue.id, player_id=4, team_number=2),
    ]
    snapshot = QueueSnapshot(
        queue=queue,
        players=players,
        player_discord_ids={1: 101, 2: 102, 3: 103, 4: 104},
    )

    embed = build_queue_embed(snapshot)

    assert embed.title == "Apostado 2V2 Match Lobby"
    assert any(field.name == "Room Setup Deadline" for field in embed.fields)
    deadline_field = next(field for field in embed.fields if field.name == "Room Setup Deadline")
    assert "Room ID" in deadline_field.value
    assert "Password" in deadline_field.value
    assert "Key" in deadline_field.value


def test_match_embed_shows_live_rooms_and_key() -> None:
    match = MatchModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        queue_id=uuid4(),
        match_number=7,
        creator_player_id=1,
        ruleset_key=RulesetKey.ESPORT,
        mode=MatchMode.FOUR_V_FOUR,
        state=MatchState.LIVE,
        team_size=4,
        room_code="ROOM-77",
        room_password="PASS-88",
        room_notes="KEY-99",
        result_channel_id=555,
        team1_voice_channel_id=556,
        team2_voice_channel_id=557,
        result_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    players = [
        MatchPlayerModel(match_id=match.id, player_id=1, team_number=1),
        MatchPlayerModel(match_id=match.id, player_id=2, team_number=1),
        MatchPlayerModel(match_id=match.id, player_id=3, team_number=2),
        MatchPlayerModel(match_id=match.id, player_id=4, team_number=2),
    ]
    snapshot = MatchSnapshot(
        match=match,
        players=players,
        votes=[],
        player_discord_ids={1: 101, 2: 102, 3: 103, 4: 104},
    )

    embed = build_match_embed(snapshot)

    assert embed.title == "Official Match #007"
    assert any(field.name == "Live Rooms" for field in embed.fields)
    assert any(field.name == "Room Access" for field in embed.fields)
    room_field = next(field for field in embed.fields if field.name == "Room Access")
    assert "Room ID: `ROOM-77`" in room_field.value
    assert "Password: `PASS-88`" in room_field.value
    assert "Key: `KEY-99`" in room_field.value
