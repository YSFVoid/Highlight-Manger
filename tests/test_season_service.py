from dataclasses import dataclass, field

import pytest

from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.models.season import SeasonRecord
from highlight_manager.services.season_service import SeasonService


@dataclass
class FakeRole:
    id: int
    name: str


@dataclass
class FakeMember:
    id: int
    roles: list[FakeRole] = field(default_factory=list)
    bot: bool = False

    async def add_roles(self, role: FakeRole, reason: str | None = None) -> None:
        if role not in self.roles:
            self.roles.append(role)

    async def remove_roles(self, role: FakeRole, reason: str | None = None) -> None:
        self.roles = [existing for existing in self.roles if existing != role]


@dataclass
class FakeGuild:
    id: int
    members: list[FakeMember]


class FakeSeasonRepository:
    def __init__(self, active: SeasonRecord) -> None:
        self.active = active
        self.ended_payload: dict | None = None

    async def get_active(self, guild_id: int) -> SeasonRecord | None:
        return self.active if self.active.guild_id == guild_id and self.active.is_active else None

    async def end_active(self, guild_id: int, ended_at, updates: dict | None = None) -> SeasonRecord | None:
        if self.active.guild_id != guild_id or not self.active.is_active:
            return None
        self.active.is_active = False
        self.active.ended_at = ended_at
        self.active.top_player_ids = list((updates or {}).get("top_player_ids", []))
        self.ended_payload = updates or {}
        return self.active

    async def get_latest(self, guild_id: int) -> SeasonRecord | None:
        return self.active

    async def create(self, season: SeasonRecord) -> SeasonRecord:
        self.active = season
        return season


class FakeProfileService:
    def __init__(self, leaderboard: list[PlayerProfile]) -> None:
        self.leaderboard = leaderboard

    async def list_leaderboard(self, guild_id: int, limit: int = 10) -> list[PlayerProfile]:
        return self.leaderboard[:limit]

    async def reset_for_new_season(self, guild, config) -> None:
        return None


class FakeConfigService:
    def __init__(self, role: FakeRole) -> None:
        self.role = role

    async def ensure_season_reward_role(self, guild, config, *, create_missing: bool):
        return config, self.role, False


@pytest.mark.asyncio
async def test_finalize_active_season_reassigns_reward_role_to_top_players() -> None:
    reward_role = FakeRole(id=55, name="Professional Highlight Player")
    members = [
        FakeMember(id=1, roles=[]),
        FakeMember(id=2, roles=[reward_role]),
        FakeMember(id=3, roles=[]),
        FakeMember(id=4, roles=[reward_role]),
    ]
    guild = FakeGuild(id=123, members=members)
    active_season = SeasonRecord(guild_id=123, season_number=2, name="Season 2")
    repository = FakeSeasonRepository(active_season)
    leaderboard = [
        PlayerProfile(guild_id=123, user_id=1, current_points=300),
        PlayerProfile(guild_id=123, user_id=3, current_points=250),
    ]
    service = SeasonService(
        repository,
        FakeProfileService(leaderboard),
        FakeConfigService(reward_role),
    )

    ended = await service.finalize_active_season(guild, GuildConfig(guild_id=123))

    assert ended is not None
    assert ended.top_player_ids == [1, 3]
    assert reward_role in members[0].roles
    assert reward_role in members[2].roles
    assert reward_role not in members[1].roles
    assert reward_role not in members[3].roles
