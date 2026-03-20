from __future__ import annotations

from enum import Enum

from highlight_manager.utils.exceptions import UserFacingError


class MatchMode(str, Enum):
    ONE_V_ONE = "1v1"
    TWO_V_TWO = "2v2"
    THREE_V_THREE = "3v3"
    FOUR_V_FOUR = "4v4"

    @property
    def team_size(self) -> int:
        return {
            MatchMode.ONE_V_ONE: 1,
            MatchMode.TWO_V_TWO: 2,
            MatchMode.THREE_V_THREE: 3,
            MatchMode.FOUR_V_FOUR: 4,
        }[self]

    @classmethod
    def from_input(cls, value: str) -> "MatchMode":
        normalized = value.strip().lower()
        for mode in cls:
            if mode.value == normalized:
                return mode
        raise UserFacingError("Mode must be one of: 1v1, 2v2, 3v3, 4v4.")


class MatchType(str, Enum):
    APOSTADO = "apostado"
    HIGHLIGHT = "highlight"

    @property
    def label(self) -> str:
        return "Apostado" if self is MatchType.APOSTADO else "Highlight"

    @classmethod
    def from_input(cls, value: str) -> "MatchType":
        normalized = value.strip().lower()
        alias_map = {
            "apos": cls.APOSTADO,
            "apostado": cls.APOSTADO,
            "high": cls.HIGHLIGHT,
            "highlight": cls.HIGHLIGHT,
        }
        match_type = alias_map.get(normalized)
        if match_type is None:
            raise UserFacingError("Type must be one of: apos, apostado, high, highlight.")
        return match_type


class MatchStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    IN_PROGRESS = "IN_PROGRESS"
    VOTING = "VOTING"
    FINALIZED = "FINALIZED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class ResultChannelBehavior(str, Enum):
    DELETE = "DELETE"
    ARCHIVE_LOCK = "ARCHIVE_LOCK"


class ResultSource(str, Enum):
    CONSENSUS = "CONSENSUS"
    FORCE_RESULT = "FORCE_RESULT"
    VOTE_TIMEOUT = "VOTE_TIMEOUT"
    CANCELED = "CANCELED"


class AuditAction(str, Enum):
    SETUP = "SETUP"
    CONFIG_UPDATED = "CONFIG_UPDATED"
    MATCH_CREATED = "MATCH_CREATED"
    MATCH_NOTIFICATION = "MATCH_NOTIFICATION"
    MATCH_JOINED = "MATCH_JOINED"
    MATCH_LEFT = "MATCH_LEFT"
    MATCH_CANCELED = "MATCH_CANCELED"
    MATCH_FULL = "MATCH_FULL"
    MATCH_FINALIZED = "MATCH_FINALIZED"
    MATCH_EXPIRED = "MATCH_EXPIRED"
    ROOM_INFO_UPDATED = "ROOM_INFO_UPDATED"
    POINTS_UPDATED = "POINTS_UPDATED"
    RANK_UPDATED = "RANK_UPDATED"
    RANK_OVERRIDE_UPDATED = "RANK_OVERRIDE_UPDATED"
    BLACKLIST_UPDATED = "BLACKLIST_UPDATED"
    SEASON_STARTED = "SEASON_STARTED"
    SEASON_ENDED = "SEASON_ENDED"
    REWARD_GRANTED = "REWARD_GRANTED"
    VOICE_OPERATION = "VOICE_OPERATION"
    RESULT_CHANNEL_OPERATION = "RESULT_CHANNEL_OPERATION"
