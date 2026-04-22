from __future__ import annotations

from highlight_manager.modules.common.enums import MatchState, QueueState


QUEUE_MUTABLE_STATES = {
    QueueState.QUEUE_OPEN,
    QueueState.FILLING,
    QueueState.READY_CHECK,
    QueueState.FULL_PENDING_ROOM_INFO,
}

QUEUE_JOINABLE_STATES = {
    QueueState.QUEUE_OPEN,
    QueueState.FILLING,
}

QUEUE_READY_STATES = {
    QueueState.READY_CHECK,
}

MATCH_RESULT_OPEN_STATES = {
    MatchState.LIVE,
    MatchState.RESULT_PENDING,
    MatchState.EXPIRED,
}
