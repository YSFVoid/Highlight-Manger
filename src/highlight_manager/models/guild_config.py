from __future__ import annotations

from datetime import datetime

from pydantic import Field

from highlight_manager.models.base import AppModel
from highlight_manager.models.common import BootstrapSummary, PointRule
from highlight_manager.models.enums import MatchMode, MatchType, ResultChannelBehavior


class ResourceNameConfig(AppModel):
    waiting_voice: str = "𝐖𝐀𝐈𝐓𝐈𝐍𝐆-𝐕𝐎𝐈𝐂𝐄"
    temp_voice_category: str = "𝐇𝐈𝐆𝐇𝐋𝐈𝐆𝐇𝐓-𝐌𝐀𝐓𝐂𝐇-𝐕𝐎𝐈𝐂𝐄𝐒"
    result_category: str = "𝐌𝐀𝐓𝐂𝐇-𝐑𝐄𝐒𝐔𝐋𝐓𝐒"
    log_channel: str = "𝐇𝐈𝐆𝐇𝐋𝐈𝐆𝐇𝐓-𝐋𝐎𝐆𝐒"
    apostado_play_channel: str = "𝐀𝐏𝐎𝐒𝐓𝐀𝐃𝐎-𝐏𝐋𝐀𝐘"
    highlight_play_channel: str = "𝐇𝐈𝐆𝐇𝐋𝐈𝐆𝐇𝐓-𝐏𝐋𝐀𝐘"


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


class GuildFeatures(AppModel):
    creator_auto_join_team1: bool = True
    auto_create_waiting_voice: bool = True
    auto_create_temp_category: bool = True
    auto_create_season_reward_role: bool = True
    auto_create_mvp_reward_role: bool = True
    nickname_rank_sync: bool = True
    bootstrap_on_first_setup: bool = True


class GuildConfig(AppModel):
    guild_id: int
    prefix: str = "!"
    resource_names: ResourceNameConfig = Field(default_factory=ResourceNameConfig)
    apostado_play_channel_id: int | None = None
    highlight_play_channel_id: int | None = None
    waiting_voice_channel_id: int | None = None
    additional_waiting_voice_channel_ids: list[int] = Field(default_factory=list)
    temp_voice_category_id: int | None = None
    result_category_id: int | None = None
    log_channel_id: int | None = None
    admin_role_ids: list[int] = Field(default_factory=list)
    staff_role_ids: list[int] = Field(default_factory=list)
    mvp_reward_role_id: int | None = None
    mvp_reward_role_name: str = "Mvp"
    mvp_winner_requirement: int = 50
    mvp_loser_requirement: int = 75
    season_reward_role_id: int | None = None
    season_reward_role_name: str = "Professional Highlight Player"
    season_reward_top_count: int = 5
    point_rules: dict[str, dict[str, PointRule]] = Field(default_factory=default_point_rules)
    result_channel_behavior: ResultChannelBehavior = ResultChannelBehavior.DELETE
    result_channel_delete_delay_seconds: int = 600
    result_channel_name_template: str = "{match_type_styled}-{match_number_styled}-𝐑𝐄𝐒𝐔𝐋𝐓"
    team1_voice_name_template: str = "{match_type_styled} {match_number_styled} • {team1_label_styled}"
    team2_voice_name_template: str = "{match_type_styled} {match_number_styled} • {team2_label_styled}"
    ping_here_on_match_create: bool = True
    ping_here_on_match_ready: bool = False
    private_match_key_required: bool = False
    queue_timeout_minutes: int = 5
    vote_timeout_minutes: int = 30
    features: GuildFeatures = Field(default_factory=GuildFeatures)
    setup_created_resources: dict[str, int] = Field(default_factory=dict)
    bootstrap_completed: bool = False
    bootstrap_completed_at: datetime | None = None
    bootstrap_last_summary: BootstrapSummary | None = None
    next_match_number: int = 1

    @property
    def all_waiting_voice_channel_ids(self) -> list[int]:
        ordered_ids: list[int] = []
        if self.waiting_voice_channel_id:
            ordered_ids.append(self.waiting_voice_channel_id)
        for channel_id in self.additional_waiting_voice_channel_ids:
            if channel_id and channel_id not in ordered_ids:
                ordered_ids.append(channel_id)
        return ordered_ids
