from types import SimpleNamespace

import pytest
from discord.ext import commands

from highlight_manager.bot import HighlightBot


class FakeLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def info(self, event: str, **kwargs) -> None:
        self.calls.append(("info", event, kwargs))

    def exception(self, event: str, **kwargs) -> None:
        self.calls.append(("exception", event, kwargs))


class FakeContext:
    def __init__(self) -> None:
        self.guild = SimpleNamespace(id=123)
        self.author = SimpleNamespace(id=456)
        self.message = SimpleNamespace(content="!unknown")
        self.command = None
        self.replies: list[str] = []

    async def reply(self, content: str) -> None:
        self.replies.append(content)


@pytest.mark.asyncio
async def test_unknown_prefix_command_is_not_reported_as_internal_error() -> None:
    bot = object.__new__(HighlightBot)
    bot.logger = FakeLogger()
    context = FakeContext()

    await HighlightBot.on_command_error(bot, context, commands.CommandNotFound("missing"))

    assert context.replies == []
    assert any(event == "prefix_command_not_found" for _, event, _ in bot.logger.calls)
