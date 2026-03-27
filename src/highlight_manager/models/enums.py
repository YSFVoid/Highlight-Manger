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


class ShopSection(str, Enum):
    DEVELOPE = "develope"
    OPTIMIZE_TOOL = "optimize-tool"
    VIDEO_EDIT = "video-edit"
    SENSI_PC = "sensi-pc"
    SENSI_IPHONE = "sensi-iphone"
    SENSI_ANDROID = "sensi-android"

    @property
    def label(self) -> str:
        return {
            ShopSection.DEVELOPE: "Develope",
            ShopSection.OPTIMIZE_TOOL: "Optimize Tool",
            ShopSection.VIDEO_EDIT: "Video Edit",
            ShopSection.SENSI_PC: "Sensi PC",
            ShopSection.SENSI_IPHONE: "Sensi iPhone",
            ShopSection.SENSI_ANDROID: "Sensi Android",
        }[self]

    @classmethod
    def from_input(cls, value: str) -> "ShopSection":
        normalized = value.strip().lower()
        alias_map = {
            "develope": cls.DEVELOPE,
            "develop": cls.DEVELOPE,
            "optimize": cls.OPTIMIZE_TOOL,
            "optimize-tool": cls.OPTIMIZE_TOOL,
            "video-edit": cls.VIDEO_EDIT,
            "video": cls.VIDEO_EDIT,
            "sensi-pc": cls.SENSI_PC,
            "pc": cls.SENSI_PC,
            "sensi-iphone": cls.SENSI_IPHONE,
            "iphone": cls.SENSI_IPHONE,
            "sensi-android": cls.SENSI_ANDROID,
            "android": cls.SENSI_ANDROID,
        }
        section = alias_map.get(normalized)
        if section is None:
            raise UserFacingError(
                "Shop section must be one of: develope, optimize-tool, video-edit, sensi-pc, sensi-iphone, sensi-android."
            )
        return section


class CoinSpendStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TournamentSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    HUGE = "HUGE"


class TournamentPhase(str, Enum):
    REGISTRATION = "REGISTRATION"
    GROUP_STAGE = "GROUP_STAGE"
    KNOCKOUT = "KNOCKOUT"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class TournamentTeamStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ELIMINATED = "ELIMINATED"
    CHAMPION = "CHAMPION"
    RUNNER_UP = "RUNNER_UP"
    CANCELED = "CANCELED"


class TournamentMatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class AuditAction(str, Enum):
    SETUP = "SETUP"
    CONFIG_UPDATED = "CONFIG_UPDATED"
    MATCH_CREATED = "MATCH_CREATED"
    MATCH_JOINED = "MATCH_JOINED"
    MATCH_LEFT = "MATCH_LEFT"
    MATCH_CANCELED = "MATCH_CANCELED"
    MATCH_FULL = "MATCH_FULL"
    MATCH_FINALIZED = "MATCH_FINALIZED"
    MATCH_EXPIRED = "MATCH_EXPIRED"
    POINTS_UPDATED = "POINTS_UPDATED"
    RANK_UPDATED = "RANK_UPDATED"
    BLACKLIST_UPDATED = "BLACKLIST_UPDATED"
    SEASON_STARTED = "SEASON_STARTED"
    SEASON_ENDED = "SEASON_ENDED"
    VOICE_OPERATION = "VOICE_OPERATION"
    RESULT_CHANNEL_OPERATION = "RESULT_CHANNEL_OPERATION"
    SHOP_UPDATED = "SHOP_UPDATED"
    COINS_UPDATED = "COINS_UPDATED"
    COIN_REQUEST_CREATED = "COIN_REQUEST_CREATED"
    COIN_REQUEST_APPROVED = "COIN_REQUEST_APPROVED"
    COIN_REQUEST_REJECTED = "COIN_REQUEST_REJECTED"
    TOURNAMENT_CREATED = "TOURNAMENT_CREATED"
    TOURNAMENT_UPDATED = "TOURNAMENT_UPDATED"
    TOURNAMENT_STARTED = "TOURNAMENT_STARTED"
    TOURNAMENT_RESULT_REPORTED = "TOURNAMENT_RESULT_REPORTED"
    TOURNAMENT_COMPLETED = "TOURNAMENT_COMPLETED"
