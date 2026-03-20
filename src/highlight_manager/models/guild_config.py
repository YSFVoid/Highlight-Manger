from __future__ import annotations

from pydantic import Field

from highlight_manager.models.base import AppModel
from datetime import datetime

from highlight_manager.models.common import BootstrapSummary, BootstrapThreshold, PointRule, RankThreshold
from highlight_manager.models.enums import MatchMode, MatchType, ResultChannelBehavior


class ResourceNameConfig(AppModel):
    waiting_voice: str = "𝗪𝗮𝗶𝘁𝗶𝗻𝗴-𝗩𝗼𝗶𝗰𝗲"
    temp_voice_category: str = "𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗠𝗮𝘁𝗰𝗵-𝗩𝗼𝗶𝗰𝗲𝘀"
    result_category: str = "𝗠𝗮𝘁𝗰𝗵-𝗥𝗲𝘀𝘂𝗹𝘁𝘀"
    log_channel: str = "𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗟𝗼𝗴𝘀"
    apostado_play_channel: str = "𝗔𝗽𝗼𝘀𝘁𝗮𝗱𝗮-𝗣𝗹𝗮𝘆"
    highlight_play_channel: str = "𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗣𝗹𝗮𝘆"


def fallback_resource_names() -> ResourceNameConfig:
    return ResourceNameConfig(
        waiting_voice="Waiting Voice",
        temp_voice_category="Highlight Match Voices",
        result_category="Match Results",
        log_channel="highlight-logs",
        apostado_play_channel="apostado-play",
        highlight_play_channel="highlight-play",
    )


def default_point_rules() -> dict[str, dict[str, PointRule]]:
    return {
        MatchType.APOSTADO.value: {
            MatchMode.ONE_V_ONE.value: PointRule(winner=10, loser=-8),
            MatchMode.TWO_V_TWO.value: PointRule(winner=10, loser=-8, winner_mvp=14, loser_mvp=-4),
            MatchMode.THREE_V_THREE.value: PointRule(
                winner=10,
                loser=-8,
                winner_mvp=14,
                loser_mvp=-4,
            ),
            MatchMode.FOUR_V_FOUR.value: PointRule(
                winner=10,
                loser=-8,
                winner_mvp=14,
                loser_mvp=-4,
            ),
            "timeout_penalty": PointRule(winner=-3, loser=-3),
        },
        MatchType.HIGHLIGHT.value: {
            MatchMode.ONE_V_ONE.value: PointRule(winner=6, loser=-4),
            MatchMode.TWO_V_TWO.value: PointRule(winner=6, loser=-5, winner_mvp=9, loser_mvp=-2),
            MatchMode.THREE_V_THREE.value: PointRule(
                winner=6,
                loser=-5,
                winner_mvp=9,
                loser_mvp=-2,
            ),
            MatchMode.FOUR_V_FOUR.value: PointRule(
                winner=6,
                loser=-5,
                winner_mvp=9,
                loser_mvp=-2,
            ),
            "timeout_penalty": PointRule(winner=-2, loser=-2),
        },
    }


def default_rank_thresholds() -> list[RankThreshold]:
    return [
        RankThreshold(rank=1, min_points=0),
        RankThreshold(rank=2, min_points=100),
        RankThreshold(rank=3, min_points=200),
        RankThreshold(rank=4, min_points=300),
        RankThreshold(rank=5, min_points=400),
        RankThreshold(rank=6, min_points=500),
        RankThreshold(rank=7, min_points=650),
        RankThreshold(rank=8, min_points=800),
        RankThreshold(rank=9, min_points=1000),
        RankThreshold(rank=10, min_points=1250),
    ]


def default_bootstrap_thresholds() -> list[BootstrapThreshold]:
    return [
        BootstrapThreshold(minimum_days=365, rank=10, starting_points=1250),
        BootstrapThreshold(minimum_days=300, rank=9, starting_points=1000),
        BootstrapThreshold(minimum_days=240, rank=8, starting_points=800),
        BootstrapThreshold(minimum_days=180, rank=7, starting_points=650),
        BootstrapThreshold(minimum_days=150, rank=6, starting_points=500),
        BootstrapThreshold(minimum_days=120, rank=5, starting_points=400),
        BootstrapThreshold(minimum_days=90, rank=4, starting_points=300),
        BootstrapThreshold(minimum_days=60, rank=3, starting_points=200),
        BootstrapThreshold(minimum_days=30, rank=2, starting_points=100),
        BootstrapThreshold(minimum_days=0, rank=1, starting_points=0),
    ]


class GuildFeatures(AppModel):
    auto_create_resources: bool = True
    creator_auto_join_team1: bool = True
    preserve_rank0: bool = True
    auto_create_waiting_voice: bool = True
    auto_create_temp_category: bool = True
    auto_create_season_reward_role: bool = True
    nickname_rank_sync: bool = True
    bootstrap_on_first_setup: bool = True


class GuildConfig(AppModel):
    guild_id: int
    prefix: str = "!"
    resource_names: ResourceNameConfig = Field(default_factory=ResourceNameConfig)
    apostado_play_channel_id: int | None = None
    highlight_play_channel_id: int | None = None
    waiting_voice_channel_id: int | None = None
    temp_voice_category_id: int | None = None
    result_category_id: int | None = None
    log_channel_id: int | None = None
    admin_role_ids: list[int] = Field(default_factory=list)
    staff_role_ids: list[int] = Field(default_factory=list)
    season_reward_role_id: int | None = None
    season_reward_role_name: str = "Professional Highlight Player"
    rank_thresholds: list[RankThreshold] = Field(default_factory=default_rank_thresholds)
    bootstrap_thresholds: list[BootstrapThreshold] = Field(default_factory=default_bootstrap_thresholds)
    point_rules: dict[str, dict[str, PointRule]] = Field(default_factory=default_point_rules)
    result_channel_behavior: ResultChannelBehavior = ResultChannelBehavior.DELETE
    result_channel_delete_delay_seconds: int = 600
    result_channel_name_template: str = "match-{match_id}-result"
    team1_voice_name_template: str = "TEAM 1 - Match #{match_id}"
    team2_voice_name_template: str = "TEAM 2 - Match #{match_id}"
    queue_timeout_minutes: int = 5
    vote_timeout_minutes: int = 30
    features: GuildFeatures = Field(default_factory=GuildFeatures)
    setup_created_resources: dict[str, int] = Field(default_factory=dict)
    bootstrap_completed: bool = False
    bootstrap_completed_at: datetime | None = None
    bootstrap_last_summary: BootstrapSummary | None = None
    next_match_number: int = 1
