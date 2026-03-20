from types import SimpleNamespace

import discord
import pytest

from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType
from highlight_manager.commands.prefix.gameplay import GameplayCog
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord, MatchRoomInfo
from highlight_manager.services.match_service import MatchService
from highlight_manager.utils.dates import minutes_from_now, utcnow
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
        self.deleted: list[tuple[int, int]] = []
        self.storage: dict[tuple[int, int], object] = {}

    async def create(self, match):
        self.created.append(match)
        self.storage[(match.guild_id, match.match_number)] = match
        return match

    async def replace(self, match):
        self.replaced.append(match)
        self.storage[(match.guild_id, match.match_number)] = match
        return match

    async def delete(self, guild_id: int, match_number: int):
        self.deleted.append((guild_id, match_number))
        self.storage.pop((guild_id, match_number), None)
        return True

    async def get(self, guild_id: int, match_number: int):
        return self.storage.get((guild_id, match_number))


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
    def __init__(self) -> None:
        self.created_channels: list[FakeTextChannel] = []
        self.synced: list[tuple[int, int]] = []
        self.deleted: list[int] = []

    async def create_private_channel(self, guild, match, config):
        channel = FakeTextChannel(500 + len(self.created_channels), guild, f"#match-{match.display_id}-result")
        guild.add_channel(channel)
        self.created_channels.append(channel)
        return channel

    async def sync_channel_access(self, guild, channel_id: int, match, config) -> None:
        self.synced.append((channel_id, match.match_number))

    async def delete_channel(self, guild, channel_id: int, match_number: int) -> None:
        self.deleted.append(channel_id)


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


class FakeTextChannel(discord.TextChannel):
    __slots__ = ("id", "guild", "mention", "sent_payloads", "fail_send", "messages", "permission_updates")

    def __init__(self, channel_id: int, guild: FakeGuild, mention: str, *, fail_send: bool = False) -> None:
        self.id = channel_id
        self.guild = guild
        self.mention = mention
        self.sent_payloads: list[dict] = []
        self.fail_send = fail_send
        self.messages: dict[int, object] = {}
        self.permission_updates: list[tuple[object, object]] = []

    async def send(self, content=None, *, embed=None, view=None):
        if self.fail_send:
            raise RuntimeError("boom")
        payload = {"content": content, "embed": embed, "view": view}
        self.sent_payloads.append(payload)
        message = FakeMessage(900 + len(self.sent_payloads), self, payload)
        self.messages[message.id] = message
        return message

    async def fetch_message(self, message_id: int):
        return self.messages[message_id]

    async def set_permissions(self, target, overwrite=None):
        self.permission_updates.append((target, overwrite))


class FakeMessage:
    def __init__(self, message_id: int, channel: FakeTextChannel, payload: dict) -> None:
        self.id = message_id
        self.channel = channel
        self.payload = payload

    async def edit(self, *, content=None, embed=None, view=None):
        self.payload = {
            "content": content if content is not None else self.payload.get("content"),
            "embed": embed if embed is not None else self.payload.get("embed"),
            "view": view if view is not None else self.payload.get("view"),
        }
        self.channel.messages[self.id] = self

    async def delete(self):
        self.channel.messages.pop(self.id, None)


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
    result_channel_service = FakeResultChannelService()
    service = MatchService(
        bot,
        repository,
        FakeConfigService(config),
        FakeProfileService(blacklisted=blacklisted),
        FakeSeasonService(),
        FakeVoteService(),
        FakeVoiceService(),
        result_channel_service,
        FakeAuditService(),
    )
    service.logger = bot.logger
    service.register_views = lambda match: None  # type: ignore[assignment]
    service._build_queue_view = lambda match: None  # type: ignore[method-assign]
    return service, guild, apostado_channel, highlight_channel, creator, repository, bot.logger


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode_input", "match_type_input", "channel_attr", "expected_normalized"),
    [
        ("1v1", "high", "highlight", "highlight"),
        ("2v2", "apos", "apostado", "apostado"),
        ("2v2", "high", "highlight", "highlight"),
        ("3v3", "high", "highlight", "highlight"),
        ("4v4", "apos", "apostado", "apostado"),
        ("4v4", "high", "highlight", "highlight"),
    ],
)
async def test_create_match_accepts_aliases_and_creates_match(
    mode_input: str,
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
        mode_input,
        match_type_input,
        raw_command_content=f"!play {mode_input} {match_type_input}",
    )

    assert result.match.match_type.value == expected_normalized
    assert result.match.mode.value == mode_input
    assert result.match.queue_opened_at is None
    assert result.match.queue_expires_at is None
    assert len(repository.created) == 1
    assert repository.created[0].creator_id == creator.id
    assert len(channel.sent_payloads) == 1
    assert channel.sent_payloads[0]["embed"].title.endswith("Match Setup")
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
        level == "exception" and event == "play_command_unexpected_failure" and kwargs["validation_stage"] == "post_room_setup_message"
        for level, event, kwargs in logger.calls
    )
    assert (123, 1) in service.repository.deleted


@pytest.mark.asyncio
async def test_submit_room_info_opens_queue_and_posts_privately() -> None:
    config = GuildConfig(
        guild_id=123,
        apostado_play_channel_id=10,
        highlight_play_channel_id=20,
        waiting_voice_channel_id=30,
        temp_voice_category_id=40,
        ping_here_on_match_create=False,
    )
    service, guild, apostado_channel, _, creator, repository, _ = build_service(config)

    created = await service.create_match(
        apostado_channel,
        guild,
        creator,
        "2v2",
        "apos",
        raw_command_content="!play 2v2 apos",
    )
    assert created.match.queue_opened_at is None

    result = await service.submit_room_info(
        guild,
        created.match.match_number,
        creator,
        room_id="123456",
        password="pw",
        private_match_key="ABCD",
    )

    assert result.match.queue_opened_at is not None
    assert result.match.queue_expires_at is not None
    assert result.match.room_info is not None
    assert "now open for players" in result.message
    public_message = apostado_channel.messages[result.match.public_message_id]
    assert public_message.payload["embed"].title == "Apostado 2v2 Match"
    result_channel_id = result.match.result_channel_id
    result_channel = guild.get_channel(result_channel_id)
    assert isinstance(result_channel, FakeTextChannel)
    assert any(payload["embed"].title == "Room Access - Match #001" for payload in result_channel.sent_payloads)
    assert repository.get is not None


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


def test_rank_command_registers_r_alias() -> None:
    cog = GameplayCog(SimpleNamespace())
    command_names = {command.name: command for command in cog.get_commands()}
    assert "rank" in command_names
    assert "r" in command_names["rank"].aliases


@pytest.mark.asyncio
async def test_room_info_is_posted_to_private_result_channel_once_per_channel() -> None:
    config = GuildConfig(
        guild_id=123,
        apostado_play_channel_id=10,
        highlight_play_channel_id=20,
        waiting_voice_channel_id=30,
        temp_voice_category_id=40,
    )
    service, guild, apostado_channel, _, creator, _, _ = build_service(config)
    result_channel = FakeTextChannel(55, guild, "#match-001-result")
    guild.add_channel(result_channel)

    match = MatchRecord(
        guild_id=123,
        match_number=1,
        creator_id=creator.id,
        mode=MatchMode.TWO_V_TWO,
        match_type=MatchType.HIGHLIGHT,
        status=MatchStatus.IN_PROGRESS,
        team1_player_ids=[creator.id],
        team2_player_ids=[77],
        result_channel_id=result_channel.id,
        created_at=utcnow(),
        queue_expires_at=minutes_from_now(5),
        room_info=MatchRoomInfo(
            room_id="123456",
            password="secret",
            private_match_key="ABCD",
            submitted_by=creator.id,
        ),
    )

    updated_match = await service._ensure_room_info_available_in_result_channel(guild, match)
    updated_match = await service._ensure_room_info_available_in_result_channel(guild, updated_match)

    assert updated_match.metadata["room_info_posted_channel_id"] == result_channel.id
    assert len(result_channel.sent_payloads) == 1
    assert result_channel.sent_payloads[0]["embed"].title == "Room Access - Match #001"
    assert apostado_channel.sent_payloads == []
