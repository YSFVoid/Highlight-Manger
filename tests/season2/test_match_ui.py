from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from highlight_manager.db.models.competitive import MatchModel, MatchPlayerModel, QueueModel, QueuePlayerModel
from highlight_manager.modules.common.enums import MatchMode, MatchResultPhase, MatchState, QueueState, RulesetKey
from highlight_manager.modules.matches.types import MatchSnapshot, QueueSnapshot
from highlight_manager.modules.matches.ui import (
    build_public_match_embed,
    build_queue_embed,
    build_result_match_embed,
)


def _field_containing(embed, name_text: str):
    return next(field for field in embed.fields if name_text in field.name)


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

    assert embed.title.endswith("Apostado 2V2 Lobby")
    assert any("Room Setup Deadline" in field.name for field in embed.fields)
    deadline_field = _field_containing(embed, "Room Setup Deadline")
    assert "Room ID" in deadline_field.value
    assert "Password" in deadline_field.value
    assert "Key" in deadline_field.value


def test_queue_embed_shows_ready_check_deadline_without_room_info_copy() -> None:
    queue = QueueModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        creator_player_id=1,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.TWO_V_TWO,
        state=QueueState.READY_CHECK,
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

    deadline_field = _field_containing(embed, "Ready Check Deadline")
    assert "press **Ready**" in deadline_field.value
    assert "Room ID" not in deadline_field.value
    assert "Password" not in deadline_field.value


def test_queue_embed_humanizes_ready_check_timeout_reason() -> None:
    queue = QueueModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        creator_player_id=1,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.ONE_V_ONE,
        state=QueueState.QUEUE_CANCELLED,
        team_size=1,
        cancel_reason="ready_check_timeout",
    )
    players = [
        QueuePlayerModel(queue_id=queue.id, player_id=1, team_number=1),
        QueuePlayerModel(queue_id=queue.id, player_id=2, team_number=2),
    ]
    snapshot = QueueSnapshot(
        queue=queue,
        players=players,
        player_discord_ids={1: 101, 2: 102},
    )

    embed = build_queue_embed(snapshot)

    cancel_field = _field_containing(embed, "Cancel Reason")
    assert "Ready check expired before everyone pressed Ready." in cancel_field.value


def test_queue_embed_humanizes_stale_queue_timeout_reason() -> None:
    queue = QueueModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        creator_player_id=1,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.TWO_V_TWO,
        state=QueueState.QUEUE_CANCELLED,
        team_size=2,
        cancel_reason="queue_timeout",
    )
    players = [
        QueuePlayerModel(queue_id=queue.id, player_id=1, team_number=1),
        QueuePlayerModel(queue_id=queue.id, player_id=2, team_number=2),
    ]
    snapshot = QueueSnapshot(
        queue=queue,
        players=players,
        player_discord_ids={1: 101, 2: 102},
    )

    embed = build_queue_embed(snapshot)

    cancel_field = _field_containing(embed, "Cancel Reason")
    assert "Queue expired before enough players joined." in cancel_field.value


def test_queue_embed_humanizes_host_left_reason() -> None:
    queue = QueueModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        creator_player_id=1,
        ruleset_key=RulesetKey.APOSTADO,
        mode=MatchMode.ONE_V_ONE,
        state=QueueState.QUEUE_CANCELLED,
        team_size=1,
        cancel_reason="host_left",
    )
    snapshot = QueueSnapshot(
        queue=queue,
        players=[],
        player_discord_ids={},
    )

    embed = build_queue_embed(snapshot)

    cancel_field = _field_containing(embed, "Cancel Reason")
    assert "Queue cancelled because the host left before match creation." in cancel_field.value


def test_public_match_embed_shows_live_rooms_and_key_without_result_controls() -> None:
    match = MatchModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        queue_id=uuid4(),
        match_number=7,
        creator_player_id=1,
        team1_captain_player_id=1,
        team2_captain_player_id=3,
        ruleset_key=RulesetKey.ESPORT,
        mode=MatchMode.FOUR_V_FOUR,
        state=MatchState.LIVE,
        result_phase=MatchResultPhase.CAPTAIN,
        team_size=4,
        room_code="ROOM-77",
        room_password="PASS-88",
        room_notes="KEY-99",
        result_channel_id=555,
        team1_voice_channel_id=556,
        team2_voice_channel_id=557,
        captain_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=3),
        fallback_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        result_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        rehost_count=0,
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

    embed = build_public_match_embed(snapshot)

    assert embed.title.endswith("Match Started")
    assert any("Live Rooms" in field.name for field in embed.fields)
    assert any("Room Access" in field.name for field in embed.fields)
    room_field = _field_containing(embed, "Room Access")
    assert "Room ID   : ROOM-77" in room_field.value
    assert "Password  : PASS-88" in room_field.value
    assert "Key       : KEY-99" in room_field.value
    assert not any("Result Progress" in field.name for field in embed.fields)
    assert embed.footer.text is not None
    assert "Official Match" in embed.footer.text


def test_result_room_embed_shows_captain_phase_details() -> None:
    now = datetime.now(timezone.utc)
    match = MatchModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        queue_id=uuid4(),
        match_number=12,
        creator_player_id=1,
        team1_captain_player_id=1,
        team2_captain_player_id=3,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.TWO_V_TWO,
        state=MatchState.RESULT_PENDING,
        result_phase=MatchResultPhase.CAPTAIN,
        team_size=2,
        room_code="ROOM-12",
        room_password="PW-12",
        room_notes=None,
        result_channel_id=5512,
        captain_deadline_at=now + timedelta(minutes=3),
        fallback_deadline_at=now + timedelta(minutes=10),
        result_deadline_at=now + timedelta(minutes=10),
        rehost_count=0,
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

    embed = build_result_match_embed(snapshot)

    assert "Result Room" in embed.title
    assert "Match #012" in embed.title
    assert any("Voting Authority" in field.name for field in embed.fields)
    assert any("Captain Window" in field.name for field in embed.fields)
    progress_field = _field_containing(embed, "Result Progress")
    assert "0/2" in progress_field.name
    assert embed.footer.text is not None
    assert "Vote Result" in embed.footer.text


def test_result_room_embed_shows_fallback_copy() -> None:
    now = datetime.now(timezone.utc)
    match = MatchModel(
        id=uuid4(),
        guild_id=1,
        season_id=1,
        queue_id=uuid4(),
        match_number=18,
        creator_player_id=1,
        team1_captain_player_id=1,
        team2_captain_player_id=3,
        ruleset_key=RulesetKey.HIGHLIGHT,
        mode=MatchMode.TWO_V_TWO,
        state=MatchState.RESULT_PENDING,
        result_phase=MatchResultPhase.FALLBACK,
        team_size=2,
        room_code="ROOM-18",
        room_password="PW-18",
        room_notes="KEY-18",
        result_channel_id=5518,
        captain_deadline_at=now,
        fallback_deadline_at=now + timedelta(minutes=10),
        result_deadline_at=now + timedelta(minutes=10),
        rehost_count=1,
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

    embed = build_result_match_embed(snapshot)

    assert "backup voting is open" in embed.description.lower()
    assert any("Fallback Window" in field.name for field in embed.fields)
    progress_field = _field_containing(embed, "Result Progress")
    assert "0/4" in progress_field.name
