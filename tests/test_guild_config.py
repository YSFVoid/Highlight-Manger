from highlight_manager.models.guild_config import GuildConfig


def test_result_channel_template_matches_expected_default() -> None:
    config = GuildConfig(guild_id=1)
    assert config.result_channel_name_template == "match-{match_id}-result"


def test_season_reward_role_defaults_match_expected_configuration() -> None:
    config = GuildConfig(guild_id=1)
    assert config.season_reward_role_name == "Professional Highlight Player"
    assert config.season_reward_role_id is None
