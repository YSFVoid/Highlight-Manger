from __future__ import annotations

import pytest

from highlight_manager.models.enums import MatchMode, MatchStatus, MatchType
from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.match import MatchRecord
from highlight_manager.services.match_service import MatchService
from highlight_manager.utils.dates import minutes_from_now, utcnow
from highlight_manager.utils.exceptions import UserFacingError


class FakeMatchRepository:
    def __init__(self, match: MatchRecord) -> None:
        self.match = match

    async def get(self, guild_id: int, match_number: int) -> MatchRecord | None:
        if self.match.guild_id == guild_id and self.match.match_number == match_number:
            return self.match
        return None

    async def replace(self, match: MatchRecord) -> MatchRecord:
        self.match = match
        return match


class FakeConfigService:
    def __init__(self, config: GuildConfig) -> None:
        self.config = config

    async def ensure_match_resources(self, guild, config):
        return self.config

    async def get_or_create(self, guild_id: int) -> GuildConfig:
        return self.config

    async def validate_ready_for_matches(self, guild_id: int) -> GuildConfig:
        return self.config

    async def is_staff(self, member) -> bool:
        return False


class FakeProfileService:
    async def require_not_blacklisted(self, guild, user_id, config):
        return None


class FakeVoteService:
    async def clear_votes(self, match) -> None:
        return None

    async def get_votes(self, match) -> list[object]:
        return []


class FakeVoiceService:
    def ensure_member_in_waiting_voice(self, member, config) -> None:
        return None

    async def create_match_voice_channels(self, guild, match, config):
        raise UserFacingError("Missing temp category permissions.")

    async def move_players_to_team_channels(self, guild, match, team1, team2):
        return []

    async def cleanup_match_voices(self, guild, match) -> None:
        return None


class FakeResultChannelService:
    async def create_private_channel(self, guild, match, config):
        raise AssertionError("Result channel should not be created after voice setup failure.")

    async def finalize_channel_behavior(self, guild, match, config) -> None:
        return None

    async def delete_channel(self, guild, channel_id, match_number) -> None:
        return None


class FakeAuditService:
    async def log(self, guild, action, message, **kwargs) -> None:
        return None


class FakeGuild:
    def __init__(self, waiting_voice_id: int) -> None:
        self.id = 1
        self._channels = {}
        self._members = {}
        self.waiting_voice_id = waiting_voice_id

    def get_channel(self, channel_id: int | None):
        return self._channels.get(channel_id)

    def get_member(self, user_id: int):
        return self._members.get(user_id)


class FakeVoiceState:
    def __init__(self, channel_id: int | None) -> None:
        self.channel = None if channel_id is None else type("Channel", (), {"id": channel_id})()


class FakeMember:
    def __init__(self, user_id: int, guild: FakeGuild, *, voice_channel_id: int | None) -> None:
        self.id = user_id
        self.guild = guild
        self.display_name = f"User {user_id}"
        self.mention = f"<@{user_id}>"
        self.voice = FakeVoiceState(voice_channel_id)


@pytest.mark.asyncio
async def test_start_full_match_requires_all_players_to_stay_in_waiting_voice() -> None:
    config = GuildConfig(guild_id=1, waiting_voice_channel_id=50, temp_voice_category_id=60)
    match = MatchRecord(
        guild_id=1,
        match_number=1,
        creator_id=10,
        mode=MatchMode.ONE_V_ONE,
        match_type=MatchType.APOSTADO,
        status=MatchStatus.FULL,
        team1_player_ids=[10],
        team2_player_ids=[20],
        created_at=utcnow(),
        queue_expires_at=minutes_from_now(5),
    )
    guild = FakeGuild(waiting_voice_id=50)
    guild._members[10] = FakeMember(10, guild, voice_channel_id=50)
    guild._members[20] = FakeMember(20, guild, voice_channel_id=None)
    service = MatchService(
        bot=None,  # type: ignore[arg-type]
        repository=FakeMatchRepository(match),
        config_service=FakeConfigService(config),
        profile_service=FakeProfileService(),
        season_service=None,  # type: ignore[arg-type]
        vote_service=FakeVoteService(),
        voice_service=FakeVoiceService(),
        result_channel_service=FakeResultChannelService(),
        audit_service=FakeAuditService(),
        coins_service=None,
    )

    with pytest.raises(UserFacingError, match="must stay in the Waiting Voice"):
        await service.start_full_match(guild, match, config)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_join_team_cancels_match_when_automatic_start_fails() -> None:
    config = GuildConfig(guild_id=1, waiting_voice_channel_id=50, temp_voice_category_id=60)
    match = MatchRecord(
        guild_id=1,
        match_number=1,
        creator_id=10,
        mode=MatchMode.ONE_V_ONE,
        match_type=MatchType.APOSTADO,
        status=MatchStatus.OPEN,
        team1_player_ids=[10],
        team2_player_ids=[],
        created_at=utcnow(),
        queue_expires_at=minutes_from_now(5),
        source_channel_id=999,
    )
    guild = FakeGuild(waiting_voice_id=50)
    guild._members[10] = FakeMember(10, guild, voice_channel_id=50)
    joining_member = FakeMember(20, guild, voice_channel_id=50)
    guild._members[20] = joining_member
    service = MatchService(
        bot=None,  # type: ignore[arg-type]
        repository=FakeMatchRepository(match),
        config_service=FakeConfigService(config),
        profile_service=FakeProfileService(),
        season_service=None,  # type: ignore[arg-type]
        vote_service=FakeVoteService(),
        voice_service=FakeVoiceService(),
        result_channel_service=FakeResultChannelService(),
        audit_service=FakeAuditService(),
        coins_service=None,
    )

    result = await service.join_team(joining_member, 1, 2)

    assert result.match.status == MatchStatus.CANCELED
    assert "automatic start failed" in result.message.lower()
