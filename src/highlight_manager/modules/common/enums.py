from __future__ import annotations

from enum import StrEnum

from highlight_manager.modules.common.exceptions import ValidationError


class RoleKind(StrEnum):
    ADMIN = "admin"
    MODERATOR = "moderator"


class ActivityKind(StrEnum):
    IDLE = "idle"
    QUEUE = "queue"
    MATCH = "match"
    TOURNAMENT = "tournament"


class SeasonStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    ENDED = "ended"
    ARCHIVED = "archived"


class QueueState(StrEnum):
    QUEUE_OPEN = "queue_open"
    FILLING = "filling"
    READY_CHECK = "ready_check"
    FULL_PENDING_ROOM_INFO = "full_pending_room_info"
    QUEUE_CANCELLED = "queue_cancelled"
    CONVERTED_TO_MATCH = "converted_to_match"


class MatchState(StrEnum):
    CREATED = "created"
    MOVING = "moving"
    LIVE = "live"
    RESULT_PENDING = "result_pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    FORCE_CLOSED = "force_closed"


class MatchResultPhase(StrEnum):
    CAPTAIN = "captain"
    FALLBACK = "fallback"
    STAFF_REVIEW = "staff_review"


class MatchPlayerResult(StrEnum):
    WIN = "win"
    LOSS = "loss"
    NONE = "none"


class RatingReason(StrEnum):
    SEASON_SEED = "season_seed"
    MATCH_RESULT = "match_result"
    ADMIN_ADJUSTMENT = "admin_adjustment"
    ROLLBACK = "rollback"


class WalletTransactionType(StrEnum):
    MATCH_PARTICIPATION = "match_participation"
    MATCH_WIN = "match_win"
    MATCH_MVP_WINNER = "match_mvp_winner"
    MATCH_MVP_LOSER = "match_mvp_loser"
    STREAK_BONUS = "streak_bonus"
    DAILY_BONUS = "daily_bonus"
    MILESTONE_BONUS = "milestone_bonus"
    PURCHASE = "purchase"
    PURCHASE_REFUND = "purchase_refund"
    TOURNAMENT_PARTICIPATION = "tournament_participation"
    TOURNAMENT_RUNNER_UP = "tournament_runner_up"
    TOURNAMENT_CHAMPION = "tournament_champion"
    ADMIN_ADJUSTMENT = "admin_adjustment"


class PurchaseStatus(StrEnum):
    COMPLETED = "completed"
    REFUNDED = "refunded"
    VOIDED = "voided"


class ShopSection(StrEnum):
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
    def from_input(cls, raw: str) -> "ShopSection":
        normalized = raw.strip().lower()
        alias_map = {
            "develope": cls.DEVELOPE,
            "develop": cls.DEVELOPE,
            "optimize": cls.OPTIMIZE_TOOL,
            "optimize-tool": cls.OPTIMIZE_TOOL,
            "video-edit": cls.VIDEO_EDIT,
            "video": cls.VIDEO_EDIT,
            "edit": cls.VIDEO_EDIT,
            "sensi-pc": cls.SENSI_PC,
            "pc": cls.SENSI_PC,
            "sensi-iphone": cls.SENSI_IPHONE,
            "iphone": cls.SENSI_IPHONE,
            "sensi-android": cls.SENSI_ANDROID,
            "android": cls.SENSI_ANDROID,
        }
        section = alias_map.get(normalized)
        if section is None:
            raise ValidationError(
                "Shop section must be one of: develope, optimize-tool, video-edit, sensi-pc, sensi-iphone, sensi-android."
            )
        return section


class TournamentFormat(StrEnum):
    SINGLE_ELIMINATION = "single_elimination"


class TournamentState(StrEnum):
    DRAFT = "draft"
    REGISTRATION = "registration"
    CHECK_IN = "check_in"
    SEEDING = "seeding"
    LIVE = "live"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TournamentTeamStatus(StrEnum):
    REGISTERED = "registered"
    CHECKED_IN = "checked_in"
    ELIMINATED = "eliminated"
    CHAMPION = "champion"
    RUNNER_UP = "runner_up"
    WITHDRAWN = "withdrawn"


class TournamentMatchState(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    RESULT_PENDING = "result_pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ModerationActionType(StrEnum):
    BLACKLIST = "blacklist"
    WARNING = "warning"
    TEMP_BLOCK = "temp_block"
    COIN_ADJUSTMENT = "coin_adjustment"
    RANK_CORRECTION = "rank_correction"
    MATCH_CANCELLATION_OVERRIDE = "match_cancellation_override"


class AuditEntityType(StrEnum):
    GUILD = "guild"
    PLAYER = "player"
    QUEUE = "queue"
    MATCH = "match"
    SEASON = "season"
    TOURNAMENT = "tournament"
    SHOP = "shop"
    WALLET = "wallet"
    CONFIG = "config"


class AuditAction(StrEnum):
    QUEUE_CREATED = "queue_created"
    QUEUE_JOINED = "queue_joined"
    QUEUE_LEFT = "queue_left"
    QUEUE_CANCELLED = "queue_cancelled"
    ROOM_INFO_SUBMITTED = "room_info_submitted"
    MATCH_CREATED = "match_created"
    MATCH_MOVED_LIVE = "match_moved_live"
    MATCH_CONFIRMED = "match_confirmed"
    MATCH_EXPIRED = "match_expired"
    MATCH_FORCE_RESULT = "match_force_result"
    MATCH_FORCE_CLOSED = "match_force_closed"
    MATCH_RESULT_FALLBACK_OPENED = "match_result_fallback_opened"
    MATCH_REHOSTED = "match_rehosted"
    COINS_ADJUSTED = "coins_adjusted"
    PURCHASE_COMPLETED = "purchase_completed"
    PURCHASE_REFUNDED = "purchase_refunded"
    SHOP_ITEM_CREATED = "shop_item_created"
    SHOP_ITEM_UPDATED = "shop_item_updated"
    TOURNAMENT_CREATED = "tournament_created"
    TOURNAMENT_UPDATED = "tournament_updated"
    TOURNAMENT_MATCH_CONFIRMED = "tournament_match_confirmed"
    MODERATION_APPLIED = "moderation_applied"
    SEASON_CREATED = "season_created"
    SEASON_ARCHIVED = "season_archived"
    PERSISTENT_VOICE_UPDATED = "persistent_voice_updated"
    PERSISTENT_VOICE_INVALID = "persistent_voice_invalid"


class RulesetKey(StrEnum):
    APOSTADO = "apostado"
    HIGHLIGHT = "highlight"
    ESPORT = "esport"

    @classmethod
    def from_input(cls, raw: str) -> "RulesetKey":
        normalized = raw.strip().lower()
        if normalized in {"apos", "apostado"}:
            return cls.APOSTADO
        if normalized in {"high", "highlight"}:
            return cls.HIGHLIGHT
        if normalized in {"es", "esport"}:
            return cls.ESPORT
        raise ValidationError("Ruleset must be one of: apos, apostado, high, highlight, es, esport.")


class MatchMode(StrEnum):
    ONE_V_ONE = "1v1"
    TWO_V_TWO = "2v2"
    THREE_V_THREE = "3v3"
    FOUR_V_FOUR = "4v4"
    SIX_V_SIX = "6v6"

    @property
    def team_size(self) -> int:
        return {
            MatchMode.ONE_V_ONE: 1,
            MatchMode.TWO_V_TWO: 2,
            MatchMode.THREE_V_THREE: 3,
            MatchMode.FOUR_V_FOUR: 4,
            MatchMode.SIX_V_SIX: 6,
        }[self]

    @classmethod
    def from_input(cls, raw: str) -> "MatchMode":
        normalized = raw.strip().lower()
        for member in cls:
            if member.value == normalized:
                return member
        raise ValidationError("Mode must be one of: 1v1, 2v2, 3v3, 4v4, 6v6.")
