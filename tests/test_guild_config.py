from highlight_manager.models.guild_config import GuildConfig


def test_result_channel_template_matches_expected_default() -> None:
    config = GuildConfig(guild_id=1)
    assert config.result_channel_name_template == "match-{match_id}-result"


def test_season_reward_role_defaults_match_expected_configuration() -> None:
    config = GuildConfig(guild_id=1)
    assert config.season_reward_role_name == "Professional Highlight Player"
    assert config.season_reward_role_id is None


def test_default_resource_names_use_styled_unicode_labels() -> None:
    config = GuildConfig(guild_id=1)
    assert config.resource_names.waiting_voice == "𝗪𝗮𝗶𝘁𝗶𝗻𝗴-𝗩𝗼𝗶𝗰𝗲"
    assert config.resource_names.apostado_play_channel == "𝗔𝗽𝗼𝘀𝘁𝗮𝗱𝗮-𝗣𝗹𝗮𝘆"
    assert config.resource_names.highlight_play_channel == "𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗣𝗹𝗮𝘆"


def test_default_rank_thresholds_support_rank_10() -> None:
    config = GuildConfig(guild_id=1)
    assert len(config.rank_thresholds) == 10
    assert config.rank_thresholds[0].rank == 1
    assert config.rank_thresholds[-1].rank == 10
    assert config.rank_thresholds[-1].min_points == 1250
