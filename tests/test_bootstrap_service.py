from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from highlight_manager.models.guild_config import GuildConfig
from highlight_manager.services.bootstrap_service import BootstrapService


@dataclass
class FakeMember:
    id: int
    display_name: str
    joined_at: datetime
    bot: bool = False


@dataclass
class FakeGuild:
    members: list[FakeMember]


class DummyProfileService:
    pass


@pytest.mark.asyncio
async def test_bootstrap_preview_uses_server_age_thresholds() -> None:
    now = datetime.now(UTC)
    guild = FakeGuild(
        members=[
            FakeMember(id=1, display_name="OldGuard", joined_at=now - timedelta(days=200)),
            FakeMember(id=2, display_name="MidPlayer", joined_at=now - timedelta(days=65)),
            FakeMember(id=3, display_name="NewJoin", joined_at=now - timedelta(days=10)),
        ],
    )
    service = BootstrapService(DummyProfileService())  # type: ignore[arg-type]
    summary, preview = await service.preview(guild, GuildConfig(guild_id=1))

    assert summary.processed_members == 3
    assert preview[0].rank == 5
    assert preview[1].rank == 3
    assert preview[2].rank == 1
