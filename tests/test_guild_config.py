from highlight_manager.models.guild_config import GuildConfig


def test_result_channel_template_matches_expected_default() -> None:
    config = GuildConfig(guild_id=1)
    assert config.result_channel_name_template == "match-{match_id}-result"


def test_reward_role_defaults_match_expected_configuration() -> None:
    config = GuildConfig(guild_id=1)
    assert config.mvp_reward_role_name == "Mvp"
    assert config.mvp_reward_role_id is None
    assert config.mvp_winner_requirement == 50
    assert config.mvp_loser_requirement == 75
    assert config.season_reward_role_name == "Professional Highlight Player"
    assert config.season_reward_role_id is None
    assert config.season_reward_top_count == 5


def test_default_resource_names_use_styled_unicode_labels() -> None:
    config = GuildConfig(guild_id=1)
    assert config.resource_names.waiting_voice == "𝗪𝗮𝗶𝘁𝗶𝗻𝗴-𝗩𝗼𝗶𝗰𝗲"
    assert config.resource_names.apostado_play_channel == "𝗔𝗽𝗼𝘀𝘁𝗮𝗱𝗼-𝗣𝗹𝗮𝘆"
    assert config.resource_names.highlight_play_channel == "𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗣𝗹𝗮𝘆"
