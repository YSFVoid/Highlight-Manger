from types import SimpleNamespace

import discord
import pytest

from highlight_manager.commands.prefix.gameplay import GameplayCog
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.services.match_service import MatchService
from highlight_manager.utils.exceptions import ConfigurationError, UserFacingError


class FakeLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def info(self, event: str, **kwargs) -> None:
        self.calls.append(("info", event, kwargs))

    def warning(self, event: str, **kwargs) -> None:
        self.calls.append(("warning", event, kwargs))

    def exception(self, event: str, **kwargs) -> None:
        self.calls.append(("exception", event, kwargs))


class FakeBot:
    def __init__(self) -> None:
        self.logger = FakeLogger()
        self.views: list[object] = []

    def add_view(self, view) -> None:
        self.views.append(view)

    def get_guild(self, guild_id: int):
        return None


class FakeMatchRepository:
    def __init__(self) -> None:
        self.created: list = []
        self.replaced: list = []

    async def create(self, match):
        self.created.append(match)
        return match

    async def replace(self, match):
        self.replaced.append(match)
        return match


class FakeConfigService:
    def __init__(self, config: GuildConfig) -> None:
        self.config = config
        self.next_match_number = 1

    async def get_or_create(self, guild_id: int) -> GuildConfig:
        return self.config

    async def ensure_match_resources(self, guild, config: GuildConfig) -> GuildConfig:
        return self.config

    async def validate_ready_for_matches(self, guild_id: int) -> GuildConfig:
        if not self.config.apostado_play_channel_id:
            raise ConfigurationError("Apostado play room is not configured. Run /setup or /config first.")
        if not self.config.highlight_play_channel_id:
            raise ConfigurationError("Highlight play room is not configured. Run /setup or /config first.")
        if not self.config.waiting_voice_channel_id:
            raise ConfigurationError("Waiting Voice channel is not configured.")
        if not self.config.temp_voice_category_id:
            raise ConfigurationError("Temporary voice category is not configured.")
        return self.config

    def validate_play_channel(self, channel, config: GuildConfig, match_type) -> None:
        allowed_channel_id = (
            config.apostado_play_channel_id
            if match_type.value == "apostado"
            else config.highlight_play_channel_id
        )
        if channel.id != allowed_channel_id:
            allowed = channel.guild.get_channel(allowed_channel_id)
            raise UserFacingError(f"You can only use this command in {allowed.mention}.")

    async def reserve_next_match_number(self, guild_id: int) -> int:
        reserved = self.next_match_number
        self.next_match_number += 1
        return reserved


class FakeProfileService:
    def __init__(self, *, blacklisted: bool = False) -> None:
        self.blacklisted = blacklisted

    async def require_not_blacklisted(self, guild, user_id: int, config: GuildConfig):
        if self.blacklisted:
            raise UserFacingError("You are blacklisted from match participation.")
        return SimpleNamespace()


class FakeSeasonService:
    async def ensure_active(self, guild_id: int):
        return SimpleNamespace(season_number=7)


class FakeVoiceService:
    def ensure_member_in_waiting_voice(self, member, config: GuildConfig) -> None:
        if not config.waiting_voice_channel_id:
            raise ConfigurationError("Waiting Voice channel is not configured.")
        if member.voice is None or member.voice.channel is None:
            raise UserFacingError("You must be in the configured Waiting Voice channel to do that.")
        if member.voice.channel.id != config.waiting_voice_channel_id:
            raise UserFacingError("You must be in the configured Waiting Voice channel to do that.")


class FakeVoteService:
    pass


class FakeResultChannelService:
    pass


class FakeAuditService:
    async def log(self, *args, **kwargs) -> None:
        return None


class FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id
        self._channels: dict[int, FakeTextChannel | SimpleNamespace] = {}
        self._members: dict[int, object] = {}

    def add_channel(self, channel) -> None:
        self._channels[channel.id] = channel

    def add_member(self, member) -> None:
        self._members[member.id] = member

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)

    def get_member(self, user_id: int):
        return self._members.get(user_id)


class FakeTextChannel(discord.abc.GuildChannel):
    __slots__ = ("id", "guild", "mention", "sent_payloads", "fail_send")

    def __init__(self, channel_id: int, guild: FakeGuild, mention: str, *, fail_send: bool = False) -> None:
        self.id = channel_id
        self.guild = guild
        self.mention = mention
        self.sent_payloads: list[dict] = []
        self.fail_send = fail_send

    async def send(self, *, embed=None, view=None):
        if self.fail_send:
            raise RuntimeError("boom")
        self.sent_payloads.append({"embed": embed, "view": view})
        return SimpleNamespace(id=900 + len(self.sent_payloads))


class FakeMember:
    def __init__(self, user_id: int, guild: FakeGuild, *, voice_channel_id: int | None) -> None:
        self.id = user_id
        self.guild = guild
        self.mention = f"<@{user_id}>"
        if voice_channel_id is None:
            self.voice = None
        else:
            self.voice = SimpleNamespace(channel=SimpleNamespace(id=voice_channel_id))


class FakeDiscordMember(discord.Member):
    __slots__ = ("id", "guild", "bot")


class FakeContext:
    def __init__(self, *, guild, author, channel, content: str) -> None:
        self.guild = guild
        self.author = author
        self.channel = channel
        self.message = SimpleNamespace(content=content)
        self.replies: list[str] = []

    async def reply(self, content: str | None = None, embed=None):
        self.replies.append(content or "<embed>")


def build_service(
    config: GuildConfig,
    *,
    blacklisted: bool = False,
    channel_fail_send: bool = False,
) -> tuple[MatchService, FakeGuild, FakeTextChannel, FakeTextChannel, FakeMember, FakeMatchRepository, FakeLogger]:
    guild = FakeGuild(123)
    apostado_channel = FakeTextChannel(10, guild, "#apostado-play", fail_send=channel_fail_send)
    highlight_channel = FakeTextChannel(20, guild, "#highlight-play")
    guild.add_channel(apostado_channel)
    guild.add_channel(highlight_channel)
    creator = FakeMember(5, guild, voice_channel_id=config.waiting_voice_channel_id)
    guild.add_member(creator)

    repository = FakeMatchRepository()
    bot = FakeBot()
    service = MatchService(
        bot,
        repository,
        FakeConfigService(config),
        FakeProfileService(blacklisted=blacklisted),
        FakeSeasonService(),
        FakeVoteService(),
        FakeVoiceService(),
        FakeResultChannelService(),
        FakeAuditService(),
    )
    service.logger = bot.logger
    service.register_views = lambda match: None  # type: ignore[assignment]
    service._build_queue_view = lambda match: None  # type: ignore[method-assign]
    return service, guild, apostado_channel, highlight_channel, creator, repository, bot.logger


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("match_type_input", "channel_attr", "expected_normalized"),
    [
        ("apos", "apostado", "apostado"),
        ("high", "highlight", "highlight"),
    ],
)
async def test_create_match_accepts_aliases_and_creates_match(
    match_type_input: str,
    channel_attr: str,
    expected_normalized: str,
) -> None:
    config = GuildConfig(
        guild_id=123,
        apostado_play_channel_id=10,
        highlight_play_channel_id=20,
        waiting_voice_channel_id=30,
        temp_voice_category_id=40,
    )
    service, guild, apostado_channel, highlight_channel, creator, repository, logger = build_service(config)
    channel = apostado_channel if channel_attr == "apostado" else highlight_channel

    result = await service.create_match(
        channel,
        guild,
        creator,
        "2v2",
        match_type_input,
        raw_command_content=f"!play 2v2 {match_type_input}",
    )

    assert result.match.match_type.value == expected_normalized
    assert result.match.mode.value == "2v2"
    assert len(repository.created) == 1
    assert repository.created[0].creator_id == creator.id
    assert any(event == "play_command_completed" for _, event, _ in logger.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("match_type_input", "channel_attr", "expected_stage"),
    [
        ("apos", "highlight", "validate_play_channel"),
        ("high", "apostado", "validate_play_channel"),
    ],
)
async def test_create_match_blocks_wrong_room_with_specific_error(
    match_type_input: str,
    channel_attr: str,
    expected_stage: str,
) -> None:
    config = GuildConfig(
        guild_id=123,
        apostado_play_channel_id=10,
        highlight_play_channel_id=20,
        waiting_voice_channel_id=30,
        temp_voice_category_id=40,
    )
    service, guild, apostado_channel, highlight_channel, creator, repository, logger = build_service(config)
    wrong_channel = highlight_channel if channel_attr == "highlight" else apostado_channel

    with pytest.raises(UserFacingError, match="You can only use this command in"):
        await service.create_match(
            wrong_channel,
            guild,
            creator,
            "2v2",
            match_type_input,
            raw_command_content=f"!play 2v2 {match_type_input}",
        )

    assert not repository.created
    assert any(
        level == "warning" and event == "play_command_validation_failed" and kwargs["validation_stage"] == expected_stage
        for level, event, kwargs in logger.calls
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("match_type_input,channel_id", [("apos", 10), ("high", 20)])
async def test_create_match_blocks_when_member_is_not_in_waiting_voice(
    match_type_input: str,
    channel_id: int,
) -> None:
    config = GuildConfig(
        guild_id=123,
        apostado_play_channel_id=10,
        highlight_play_channel_id=20,
        waiting_voice_channel_id=30,
        temp_voice_category_id=40,
    )
    service, guild, apostado_channel, highlight_channel, creator, repository, logger = build_service(config)
    creator.voice = None
    channel = apostado_channel if channel_id == 10 else highlight_channel

    with pytest.raises(UserFacingError, match="You must be in the configured Waiting Voice channel"):
        await service.create_match(
            channel,
            guild,
            creator,
            "2v2",
            match_type_input,
            raw_command_content=f"!play 2v2 {match_type_input}",
        )

    assert not repository.created
    assert any(
        level == "warning" and event == "play_command_validation_failed" and kwargs["validation_stage"] == "validate_waiting_voice"
        for level, event, kwargs in logger.calls
    )


@pytest.mark.asyncio
async def test_create_match_rejects_invalid_type_before_match_creation() -> None:
    config = GuildConfig(
        guild_id=123,
        apostado_play_channel_id=10,
        highlight_play_channel_id=20,
        waiting_voice_channel_id=30,
        temp_voice_category_id=40,
    )
    service, guild, apostado_channel, _, creator, repository, logger = build_service(config)

    with pytest.raises(UserFacingError, match="Type must be one of: apos, apostado, high, highlight."):
        await service.create_match(
            apostado_channel,
            guild,
            creator,
            "2v2",
            "weird",
            raw_command_content="!play 2v2 weird",
        )

    assert not repository.created
    assert any(
        level == "warning" and event == "play_command_validation_failed" and kwargs["validation_stage"] == "normalize_type"
        for level, event, kwargs in logger.calls
    )


@pytest.mark.asyncio
async def test_create_match_logs_traceback_context_on_unexpected_failure() -> None:
    config = GuildConfig(
        guild_id=123,
        apostado_play_channel_id=10,
        highlight_play_channel_id=20,
        waiting_voice_channel_id=30,
        temp_voice_category_id=40,
    )
    service, guild, apostado_channel, _, creator, _, logger = build_service(config, channel_fail_send=True)

    with pytest.raises(RuntimeError, match="boom"):
        await service.create_match(
            apostado_channel,
            guild,
            creator,
            "2v2",
            "apos",
            raw_command_content="!play 2v2 apos",
        )

    assert any(
        level == "exception" and event == "play_command_unexpected_failure" and kwargs["validation_stage"] == "post_public_message"
        for level, event, kwargs in logger.calls
    )


@pytest.mark.asyncio
async def test_play_command_replies_with_clean_internal_error_on_unexpected_failure() -> None:
    bot = SimpleNamespace(
        match_service=SimpleNamespace(),
        logger=FakeLogger(),
    )

    async def fail_create_match(*args, **kwargs):
        raise RuntimeError("boom")

    bot.match_service.create_match = fail_create_match
    cog = GameplayCog(bot)
    cog.logger = FakeLogger()
    author = object.__new__(FakeDiscordMember)
    author.id = 5
    author.guild = SimpleNamespace(id=123)
    author.bot = False
    ctx = FakeContext(
        guild=SimpleNamespace(id=123),
        author=author,
        channel=SimpleNamespace(id=10),
        content="!play 2v2 apos",
    )

    await GameplayCog.play.callback(cog, ctx, "2v2", "apos")

    assert ctx.replies == ["I hit an internal error while processing that request."]
    assert any(event == "play_command_handler_failed" for _, event, _ in cog.logger.calls)
