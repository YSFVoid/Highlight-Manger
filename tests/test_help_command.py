from types import SimpleNamespace

import pytest

from highlight_manager.commands.prefix.gameplay import GameplayCog
from highlight_manager.models.guild_config import GuildConfig


class FakeConfigService:
    async def get_or_create(self, guild_id: int) -> GuildConfig:
        return GuildConfig(guild_id=guild_id, prefix="!")


class FakeContext:
    def __init__(self) -> None:
        self.guild = SimpleNamespace(id=123)
        self.author = SimpleNamespace(id=456)
        self.channel = SimpleNamespace(id=789)
        self.message = SimpleNamespace(content="!help")
        self.replies: list[dict] = []

    async def reply(self, content=None, *, embed=None, view=None):
        self.replies.append({"content": content, "embed": embed, "view": view})


@pytest.mark.asyncio
async def test_help_command_lists_supported_prefix_commands() -> None:
    cog = GameplayCog(SimpleNamespace(config_service=FakeConfigService()))
    ctx = FakeContext()

    await GameplayCog.help_command.callback(cog, ctx)

    assert len(ctx.replies) == 1
    embed = ctx.replies[0]["embed"]
    assert embed is not None
    assert embed.title == "Prefix Command Guide"
    fields = {field.name: field.value for field in embed.fields}
    assert "`!play <mode> <type>`" in fields["Match Queue"]
    assert "`!profile`" in fields["Player Commands"]
    assert "`!rank`" in fields["Player Commands"]
    assert "`!r`" in fields["Player Commands"]
    assert "`!leaderboard`" in fields["Player Commands"]
    assert "`!top`" in fields["Player Commands"]
    assert "`!stats [user]`" in fields["Player Commands"]
