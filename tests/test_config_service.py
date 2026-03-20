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


def build_service() -> ConfigService:
    settings = SimpleNamespace(default_prefix="!", result_channel_delete_delay_seconds=600)
    return ConfigService(repository=None, settings=settings)  # type: ignore[arg-type]


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
