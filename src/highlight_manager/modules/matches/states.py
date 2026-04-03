from __future__ import annotations

from highlight_manager.modules.common.enums import MatchState, QueueState


QUEUE_MUTABLE_STATES = {
    QueueState.QUEUE_OPEN,
    QueueState.FILLING,
    QueueState.FULL_PENDING_ROOM_INFO,
}

QUEUE_JOINABLE_STATES = {
    QueueState.QUEUE_OPEN,
    QueueState.FILLING,
}

MATCH_RESULT_OPEN_STATES = {
    MatchState.LIVE,
    MatchState.RESULT_PENDING,
    MatchState.EXPIRED,
}
