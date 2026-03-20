from dataclasses import dataclass, field

import pytest

from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.models.profile import PlayerProfile
from highlight_manager.services.reward_service import RewardService


@dataclass(eq=True, frozen=True)
class FakeRole:
    id: int
    name: str

    @property
    def mention(self) -> str:
        return f"@{self.name}"

    def __ge__(self, other) -> bool:
        return False


@dataclass
class FakePermissions:
    manage_roles: bool = True


@dataclass
class FakeBotMember:
    guild_permissions: FakePermissions = field(default_factory=FakePermissions)
    top_role: int = 10


@dataclass
class FakeMember:
    id: int
    roles: list[FakeRole] = field(default_factory=list)
    top_role: int = 1

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    async def add_roles(self, role: FakeRole, reason: str | None = None) -> None:
        self.roles.append(role)


@dataclass
class FakeGuild:
    id: int
    members: list[FakeMember]
    me: FakeBotMember = field(default_factory=FakeBotMember)
    owner: object = field(default_factory=object)

    def get_member(self, user_id: int):
        for member in self.members:
            if member.id == user_id:
                return member
        return None


class FakeConfigService:
    def __init__(self, role: FakeRole) -> None:
        self.role = role

    async def ensure_mvp_reward_role(self, guild, config, *, create_missing: bool):
        return config, self.role, False


class FakeAuditService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def log(self, guild, action, message: str, **kwargs) -> None:
        self.calls.append({"guild": guild.id, "action": action.value, "message": message, **kwargs})


@pytest.mark.asyncio
async def test_sync_mvp_role_if_qualified_grants_role_once_threshold_is_met() -> None:
    role = FakeRole(id=99, name="Mvp")
    member = FakeMember(id=5)
    guild = FakeGuild(id=123, members=[member])
    audit_service = FakeAuditService()
    service = RewardService(FakeConfigService(role), audit_service)
    profile = PlayerProfile(guild_id=123, user_id=5, mvp_winner_count=50)

    awarded = await service.sync_mvp_role_if_qualified(guild, profile, GuildConfig(guild_id=123))

    assert awarded is True
    assert role in member.roles
    assert audit_service.calls[0]["action"] == "REWARD_GRANTED"
