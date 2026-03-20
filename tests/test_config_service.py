from types import SimpleNamespace

import discord
import pytest

from highlight_manager.models.enums import MatchType
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.services.config_service import ConfigService
from highlight_manager.utils.exceptions import UserFacingError


class FakeChannel(discord.TextChannel):
    __slots__ = ("id", "guild", "mention")

    def __init__(self, channel_id: int, guild, mention: str) -> None:
        self.id = channel_id
        self.guild = guild
        self.mention = mention


class FakeGuild:
    def __init__(self, channels: dict[int, FakeChannel]) -> None:
        self.id = 1
        self._channels = channels

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)


class FakeRepository:
    def __init__(self, config: GuildConfig | None = None) -> None:
        self.config = config

    async def get(self, guild_id: int) -> GuildConfig | None:
        return self.config

    async def upsert(self, config: GuildConfig) -> GuildConfig:
        self.config = config
        return config


def build_service(repository=None) -> ConfigService:
    settings = SimpleNamespace(default_prefix="!", result_channel_delete_delay_seconds=600)
    return ConfigService(repository=repository, settings=settings)  # type: ignore[arg-type]


def test_validate_play_channel_allows_configured_match_room() -> None:
    allowed = FakeChannel(10, None, "#apostado-play")
    guild = FakeGuild({10: allowed})
    allowed.guild = guild
    config = GuildConfig(guild_id=1, apostado_play_channel_id=10, highlight_play_channel_id=20)

    build_service().validate_play_channel(allowed, config, MatchType.APOSTADO)


def test_validate_play_channel_blocks_wrong_room_with_clear_message() -> None:
    allowed = FakeChannel(10, None, "#apostado-play")
    wrong = FakeChannel(99, None, "#general")
    guild = FakeGuild({10: allowed, 99: wrong})
    allowed.guild = guild
    wrong.guild = guild
    config = GuildConfig(guild_id=1, apostado_play_channel_id=10, highlight_play_channel_id=20)

    with pytest.raises(UserFacingError, match="You can only use this command in #apostado-play\\."):
        build_service().validate_play_channel(wrong, config, MatchType.APOSTADO)


@pytest.mark.asyncio
async def test_get_or_create_migrates_legacy_name_templates_and_mojibake_resource_names() -> None:
    legacy = GuildConfig(
        guild_id=1,
        result_channel_name_template="match-{match_id}-result",
        team1_voice_name_template="TEAM 1 - Match #{match_id}",
        team2_voice_name_template="TEAM 2 - Match #{match_id}",
    )
    legacy.resource_names.waiting_voice = "ð—ªð—®ð—¶ð˜ð—¶ð—»ð—´-ð—©ð—¼ð—¶ð—°ð—²"
    repository = FakeRepository(legacy)

    migrated = await build_service(repository).get_or_create(1)

    assert migrated.result_channel_name_template == "{match_type_styled}-{match_number_styled}-𝐑𝐄𝐒𝐔𝐋𝐓"
    assert migrated.team1_voice_name_template == "{match_type_styled} {match_number_styled} • {team1_label_styled}"
    assert migrated.team2_voice_name_template == "{match_type_styled} {match_number_styled} • {team2_label_styled}"
    assert migrated.resource_names.waiting_voice == "𝐖𝐀𝐈𝐓𝐈𝐍𝐆-𝐕𝐎𝐈𝐂𝐄"
