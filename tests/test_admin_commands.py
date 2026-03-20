from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands

from highlight_manager.commands.slash.admin import register_admin_commands
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.season import SeasonRecord


class FakeLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def info(self, event: str, **kwargs) -> None:
        self.calls.append(("info", event, kwargs))

    def warning(self, event: str, **kwargs) -> None:
        self.calls.append(("warning", event, kwargs))

    def exception(self, event: str, **kwargs) -> None:
        self.calls.append(("exception", event, kwargs))


class FakeResponse:
    def __init__(self) -> None:
        self.defer_called = False
        self.messages: list[dict] = []

    def is_done(self) -> bool:
        return self.defer_called or bool(self.messages)

    async def send_message(self, content=None, embed=None, ephemeral: bool = False):
        self.messages.append({"content": content, "embed": embed, "ephemeral": ephemeral})

    async def defer(self, *, ephemeral: bool = False, thinking: bool = False):
        self.defer_called = True
        self.defer_kwargs = {"ephemeral": ephemeral, "thinking": thinking}


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send(self, content=None, embed=None, ephemeral: bool = False):
        self.messages.append({"content": content, "embed": embed, "ephemeral": ephemeral})


class FakeInteraction:
    def __init__(self, *, guild, user) -> None:
        self.guild = guild
        self.user = user
        self.response = FakeResponse()
        self.followup = FakeFollowup()
        self.command = None


class FakeDiscordMember(discord.Member):
    __slots__ = ("id", "guild", "bot", "guild_permissions")


class FakeConfigService:
    def __init__(self, *, staff_allowed: bool) -> None:
        self.staff_allowed = staff_allowed
        self.config = GuildConfig(guild_id=123)

    async def is_staff(self, member) -> bool:
        return self.staff_allowed

    async def get_or_create(self, guild_id: int) -> GuildConfig:
        return self.config

    async def get(self, guild_id: int) -> GuildConfig | None:
        return self.config


class FakeAuditService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def log(self, guild, action, message: str, **kwargs) -> None:
        self.calls.append({"guild_id": guild.id, "action": action.value, "message": message, **kwargs})


class FakeSeasonService:
    def __init__(self, interaction: FakeInteraction) -> None:
        self.interaction = interaction
        self.active_before = SeasonRecord(guild_id=123, season_number=2, name="Season 2")
        self.start_result = SeasonRecord(guild_id=123, season_number=3, name="Season 3")
        self.end_result = SeasonRecord(guild_id=123, season_number=2, name="Season 2", top_player_ids=[1, 2, 3, 4, 5], is_active=False)
        self.raise_on_end = False

    async def get_active(self, guild_id: int):
        return self.active_before

    async def start_new_season(self, guild, config, *, name: str | None = None):
        assert self.interaction.response.defer_called is True
        return SeasonRecord(
            guild_id=guild.id,
            season_number=self.start_result.season_number,
            name=name or self.start_result.name,
        )

    async def end_active(self, guild, config):
        assert self.interaction.response.defer_called is True
        if self.raise_on_end:
            raise RuntimeError("boom")
        return self.end_result


def build_bot(interaction: FakeInteraction, *, staff_allowed: bool = True):
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    bot.logger = FakeLogger()
    bot.config_service = FakeConfigService(staff_allowed=staff_allowed)
    bot.season_service = FakeSeasonService(interaction)
    bot.audit_service = FakeAuditService()
    bot.setup_service = SimpleNamespace()
    bot.bootstrap_service = SimpleNamespace()
    bot.profile_service = SimpleNamespace()
    bot.match_service = SimpleNamespace()
    register_admin_commands(bot)
    return bot


def get_subcommand(bot: commands.Bot, group_name: str, command_name: str):
    group = bot.tree.get_command(group_name)
    return group.get_command(command_name)


def build_interaction() -> FakeInteraction:
    guild = SimpleNamespace(id=123)
    member = object.__new__(FakeDiscordMember)
    member.id = 77
    member.guild = guild
    member.bot = False
    member.guild_permissions = SimpleNamespace(administrator=False, manage_guild=False)
    return FakeInteraction(guild=guild, user=member)


@pytest.mark.asyncio
async def test_season_start_defers_before_work_and_uses_followup_response() -> None:
    interaction = build_interaction()
    bot = build_bot(interaction)
    command = get_subcommand(bot, "season", "start")

    await command.callback(interaction, None)

    assert interaction.response.defer_called is True
    assert interaction.followup.messages[0]["content"] == "Started **Season 3**."
    assert any(event == "season_command_requested" for _, event, _ in bot.logger.calls)
    assert any(event == "season_command_completed" for _, event, _ in bot.logger.calls)


@pytest.mark.asyncio
async def test_season_end_defers_and_logs_reward_metadata() -> None:
    interaction = build_interaction()
    bot = build_bot(interaction)
    command = get_subcommand(bot, "season", "end")

    await command.callback(interaction)

    assert interaction.response.defer_called is True
    assert "synced the Professional Highlight Player reward for **5** player(s)." in interaction.followup.messages[0]["content"]
    assert any(
        event == "season_command_completed" and kwargs.get("reward_count") == 5
        for _, event, kwargs in bot.logger.calls
    )


@pytest.mark.asyncio
async def test_season_start_permission_denial_after_defer_responds_cleanly() -> None:
    interaction = build_interaction()
    bot = build_bot(interaction, staff_allowed=False)
    command = get_subcommand(bot, "season", "start")

    await command.callback(interaction, None)

    assert interaction.response.defer_called is True
    assert interaction.followup.messages[0]["content"] == "You do not have permission to use this command."
    assert any(event == "season_command_permission_denied" for _, event, _ in bot.logger.calls)


@pytest.mark.asyncio
async def test_season_end_failure_after_defer_returns_handled_error() -> None:
    interaction = build_interaction()
    bot = build_bot(interaction)
    bot.season_service.raise_on_end = True
    command = get_subcommand(bot, "season", "end")

    await command.callback(interaction)

    assert interaction.response.defer_called is True
    assert interaction.followup.messages[0]["content"] == "I hit an internal error while processing that request."
    assert any(level == "exception" and event == "season_command_failed" for level, event, _ in bot.logger.calls)
