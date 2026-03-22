from types import SimpleNamespace

import discord
import pytest

from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.services.voice_service import VoiceService
from highlight_manager.utils.dates import utcnow


class FakeGuild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id
        self._channels: dict[int, object] = {}
        self._members: dict[int, object] = {}

    def add_channel(self, channel) -> None:
        self._channels[channel.id] = channel

    def add_member(self, member) -> None:
        self._members[member.id] = member

    def get_channel(self, channel_id: int):
        return self._channels.get(channel_id)

    async def fetch_channel(self, channel_id: int):
        channel = self._channels.get(channel_id)
        if channel is None:
            raise KeyError(channel_id)
        return channel

    def get_member(self, user_id: int):
        return self._members.get(user_id)


class FakeVoiceChannel(discord.VoiceChannel):
    __slots__ = ("id", "guild", "mention", "deleted", "move_log")

    def __init__(self, channel_id: int, guild: FakeGuild, mention: str) -> None:
        self.id = channel_id
        self.guild = guild
        self.mention = mention
        self.deleted = False
        self.move_log: list[int] = []

    async def delete(self, *, reason=None):
        self.deleted = True


class FakeMember:
    def __init__(self, user_id: int, guild: FakeGuild, *, voice_channel_id: int | None) -> None:
        self.id = user_id
        self.guild = guild
        self.mention = f"<@{user_id}>"
        if voice_channel_id is None:
            self.voice = None
        else:
            self.voice = SimpleNamespace(channel=SimpleNamespace(id=voice_channel_id))

    async def move_to(self, channel, *, reason=None):
        self.voice = SimpleNamespace(channel=channel)
        if hasattr(channel, "move_log"):
            channel.move_log.append(self.id)


@pytest.mark.asyncio
async def test_move_players_to_waiting_voice_fetches_uncached_waiting_channel() -> None:
    service = VoiceService()
    guild = FakeGuild(123)
    waiting_channel = FakeVoiceChannel(30, guild, "Waiting")
    team1_channel = FakeVoiceChannel(40, guild, "Team 1")
    team2_channel = FakeVoiceChannel(41, guild, "Team 2")
    guild.add_channel(waiting_channel)
    guild.add_channel(team1_channel)
    guild.add_channel(team2_channel)
    player1 = FakeMember(5, guild, voice_channel_id=40)
    player2 = FakeMember(77, guild, voice_channel_id=41)
    guild.add_member(player1)
    guild.add_member(player2)

    original_get_channel = guild.get_channel

    def cache_miss(channel_id: int):
        if channel_id == 30:
            return None
        return original_get_channel(channel_id)

    guild.get_channel = cache_miss  # type: ignore[assignment]

    match = MatchRecord(
        guild_id=123,
        match_number=9,
        creator_id=5,
        mode=MatchMode.ONE_V_ONE,
        match_type=MatchType.APOSTADO,
        status=MatchStatus.IN_PROGRESS,
        team1_player_ids=[5],
        team2_player_ids=[77],
        waiting_voice_channel_id=30,
        team1_voice_channel_id=40,
        team2_voice_channel_id=41,
        created_at=utcnow(),
    )
    config = GuildConfig(guild_id=123, waiting_voice_channel_id=30)

    warnings = await service.move_players_to_waiting_voice(guild, match, config)

    assert warnings == []
    assert waiting_channel.move_log == [5, 77]


def test_ensure_member_in_waiting_voice_accepts_additional_waiting_voice_channels() -> None:
    service = VoiceService()
    guild = FakeGuild(123)
    member = FakeMember(5, guild, voice_channel_id=31)
    config = GuildConfig(
        guild_id=123,
        waiting_voice_channel_id=30,
        additional_waiting_voice_channel_ids=[31, 32],
    )

    service.ensure_member_in_waiting_voice(member, config)


@pytest.mark.asyncio
async def test_cleanup_match_voices_fetches_uncached_temp_channels() -> None:
    service = VoiceService()
    guild = FakeGuild(123)
    team1_channel = FakeVoiceChannel(40, guild, "Team 1")
    team2_channel = FakeVoiceChannel(41, guild, "Team 2")
    guild.add_channel(team1_channel)
    guild.add_channel(team2_channel)

    original_get_channel = guild.get_channel

    def cache_miss(channel_id: int):
        if channel_id in {40, 41}:
            return None
        return original_get_channel(channel_id)

    guild.get_channel = cache_miss  # type: ignore[assignment]

    match = MatchRecord(
        guild_id=123,
        match_number=9,
        creator_id=5,
        mode=MatchMode.ONE_V_ONE,
        match_type=MatchType.APOSTADO,
        status=MatchStatus.FINALIZED,
        team1_player_ids=[5],
        team2_player_ids=[77],
        team1_voice_channel_id=40,
        team2_voice_channel_id=41,
        created_at=utcnow(),
    )

    await service.cleanup_match_voices(guild, match)

    assert team1_channel.deleted is True
    assert team2_channel.deleted is True
