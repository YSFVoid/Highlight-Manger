from highlight_manager.models.guild_config import GuildConfig


def test_result_channel_template_matches_expected_default() -> None:
    config = GuildConfig(guild_id=1)
    assert config.result_channel_name_template == "{match_type_styled}-{match_number_styled}-𝐑𝐄𝐒𝐔𝐋𝐓"
    assert config.team1_voice_name_template == "{match_type_styled} {match_number_styled} • {team1_label_styled}"
    assert config.team2_voice_name_template == "{match_type_styled} {match_number_styled} • {team2_label_styled}"


def test_reward_role_defaults_match_expected_configuration() -> None:
    config = GuildConfig(guild_id=1)
    assert config.mvp_reward_role_name == "Mvp"
    assert config.mvp_reward_role_id is None
    assert config.mvp_winner_requirement == 50
    assert config.mvp_loser_requirement == 75
    assert config.season_reward_role_name == "Professional Highlight Player"
    assert config.season_reward_role_id is None
    assert config.season_reward_top_count == 5


def test_match_announcement_defaults_open_queue_ping_only() -> None:
    config = GuildConfig(guild_id=1)
    assert config.ping_here_on_match_create is True
    assert config.ping_here_on_match_ready is False
    assert config.private_match_key_required is False


def test_default_resource_names_use_styled_unicode_labels() -> None:
    config = GuildConfig(guild_id=1)
    assert config.resource_names.waiting_voice == "𝐖𝐀𝐈𝐓𝐈𝐍𝐆-𝐕𝐎𝐈𝐂𝐄"
    assert config.resource_names.apostado_play_channel == "𝐀𝐏𝐎𝐒𝐓𝐀𝐃𝐎-𝐏𝐋𝐀𝐘"
    assert config.resource_names.highlight_play_channel == "𝐇𝐈𝐆𝐇𝐋𝐈𝐆𝐇𝐓-𝐏𝐋𝐀𝐘"
