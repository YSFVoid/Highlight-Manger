from __future__ import annotations

import inspect

import pytest
from discord.ext import commands

from highlight_manager.bot import HighlightBot
from highlight_manager.config.settings import Settings


class FakeContext:
    def __init__(self) -> None:
        self.guild = None
        self.command = type("Command", (), {"qualified_name": "play"})()
        self.replies = []

    async def reply(self, message: str) -> None:
        self.replies.append(message)


@pytest.mark.asyncio
async def test_on_command_error_returns_usage_for_play_missing_argument() -> None:
    bot = HighlightBot.__new__(HighlightBot)
    bot.settings = Settings(DISCORD_TOKEN="token", MONGODB_URI="mongodb://localhost")
    bot.config_service = None
    bot.logger = type("Logger", (), {"exception": lambda *args, **kwargs: None})()

    def play(mode, match_type):
        return None

    param = list(inspect.signature(play).parameters.values())[1]
    error = commands.MissingRequiredArgument(param=param)
    context = FakeContext()

    await HighlightBot.on_command_error(bot, context, error)

    assert context.replies == ["Usage: `!play <mode> <type>`. Example: `!play 4v4 apos`."]
