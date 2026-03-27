from __future__ import annotations

from dataclasses import dataclass

import pytest

import highlight_manager.services.config_service as config_service_module
from highlight_manager.bot import HighlightBot
from highlight_manager.config.settings import Settings
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.services.config_service import ConfigService


class FakeConfigRepository:
    def __init__(self) -> None:
        self.storage: dict[int, GuildConfig] = {}

    async def get(self, guild_id: int) -> GuildConfig | None:
        return self.storage.get(guild_id)

    async def upsert(self, config: GuildConfig) -> GuildConfig:
        self.storage[config.guild_id] = config
        return config

    async def reserve_next_match_number(self, guild_id: int, defaults: GuildConfig) -> int:
        config = self.storage.get(guild_id, defaults)
        match_number = config.next_match_number
        config.next_match_number += 1
        self.storage[guild_id] = config
        return match_number


@dataclass
class FakeTextChannel:
    id: int
    name: str


class FakeGuild:
    def __init__(self, channels: list[FakeTextChannel]) -> None:
        self.id = 1
        self.channels = channels

    def get_channel(self, channel_id: int | None):
        for channel in self.channels:
            if channel.id == channel_id:
                return channel
        return None


def test_match_channel_allowlist_accepts_only_valid_play_command() -> None:
    bot = HighlightBot.__new__(HighlightBot)
    config = GuildConfig(
        guild_id=1,
        prefix="!",
        apostado_channel_id=100,
        highlight_channel_id=200,
    )

    assert bot._is_allowed_match_channel_message("!play 3v3 apostado", config, 100) is True
    assert bot._is_allowed_match_channel_message("!play 3v3 highlight", config, 200) is True
    assert bot._is_allowed_match_channel_message("w", config, 200) is False
    assert bot._is_allowed_match_channel_message("!profile", config, 200) is False
    assert bot._is_allowed_match_channel_message("!play 3v3", config, 200) is False
    assert bot._is_allowed_match_channel_message("!play badmode highlight", config, 200) is False
    assert bot._is_allowed_match_channel_message("!play 3v3 highlight extra", config, 200) is False
    assert bot._is_allowed_match_channel_message("!play 3v3 apostado", config, 200) is False


@pytest.mark.asyncio
async def test_backfill_play_channels_resolves_named_channels() -> None:
    config_service_module.discord.TextChannel = FakeTextChannel
    repository = FakeConfigRepository()
    settings = Settings(DISCORD_TOKEN="token", MONGODB_URI="mongodb://localhost")
    service = ConfigService(repository, settings)
    config = GuildConfig(guild_id=1, prefix="!")
    await repository.upsert(config)

    guild = FakeGuild(
        [
            FakeTextChannel(id=100, name="apostado-play"),
            FakeTextChannel(id=200, name="highlight-play"),
        ]
    )

    updated = await service.backfill_play_channels(guild)  # type: ignore[arg-type]

    assert updated.apostado_channel_id == 100
    assert updated.highlight_channel_id == 200
