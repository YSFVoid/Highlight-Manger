from __future__ import annotations

import inspect
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.bot import HighlightBot
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import MatchMode, RulesetKey
from highlight_manager.modules.common.exceptions import ValidationError
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'match-ping-targets.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@dataclass(slots=True)
class DummyRole:
    id: int
    mention: str


class DummyGuild:
    def __init__(self, role_map: dict[int, DummyRole] | None = None) -> None:
        self.id = 98765
        self.name = "Highlight"
        self._role_map = role_map or {}

    def get_role(self, role_id: int) -> DummyRole | None:
        return self._role_map.get(role_id)


class DummyLogger:
    def __init__(self) -> None:
        self.warnings: list[tuple[str, dict[str, object]]] = []

    def warning(self, event: str, **kwargs) -> None:
        self.warnings.append((event, kwargs))


class DummyGuildService:
    def __init__(self, settings) -> None:
        self._settings = settings

    async def ensure_guild(self, _repository, _discord_guild_id: int, _name: str | None):
        return SimpleNamespace(settings=self._settings)


class DummySessionContext:
    async def __aenter__(self):
        return SimpleNamespace(guilds=object())

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class DummyRuntime:
    def __init__(self, settings) -> None:
        self.services = SimpleNamespace(guilds=DummyGuildService(settings))

    def session(self) -> DummySessionContext:
        return DummySessionContext()


def _make_settings(*, apostado: str | None = "here", highlight: str | None = "here", esport: str | None = "here"):
    return SimpleNamespace(
        apostado_match_ping_target=apostado,
        highlight_match_ping_target=highlight,
        esport_match_ping_target=esport,
    )


def _make_snapshot(*, ruleset: RulesetKey = RulesetKey.APOSTADO):
    return SimpleNamespace(
        match=SimpleNamespace(
            id=uuid4(),
            ruleset_key=ruleset,
            match_number=7,
            mode=MatchMode.TWO_V_TWO,
            result_channel_id=111,
        )
    )


def _make_bot(settings) -> HighlightBot:
    bot = object.__new__(HighlightBot)
    bot.runtime = DummyRuntime(settings)
    bot.logger = DummyLogger()
    return bot


@pytest.mark.asyncio
async def test_new_guild_settings_default_match_ping_targets_to_here(session: AsyncSession) -> None:
    guild_service = GuildService(Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db"))
    bundle = await guild_service.ensure_guild(GuildRepository(session), 4567, "Highlight")

    assert bundle.settings.apostado_match_ping_target == "here"
    assert bundle.settings.highlight_match_ping_target == "here"
    assert bundle.settings.esport_match_ping_target == "here"


def test_match_ping_helpers_normalize_and_format_targets() -> None:
    settings = _make_settings(apostado=None, highlight="", esport="role:42")
    guild = DummyGuild({42: DummyRole(id=42, mention="<@&42>")})

    assert HighlightBot.get_match_ping_target(settings, RulesetKey.APOSTADO) == "here"
    assert HighlightBot.get_match_ping_target(settings, RulesetKey.HIGHLIGHT) == "here"
    assert HighlightBot.get_match_ping_target(settings, RulesetKey.ESPORT) == "role:42"

    assert HighlightBot.format_match_ping_target(guild, "none") == "No ping"
    assert HighlightBot.format_match_ping_target(guild, "here") == "@here"
    assert HighlightBot.format_match_ping_target(guild, "role:42") == "<@&42>"
    assert HighlightBot.format_match_ping_target(guild, "role:77") == "`role:77` (missing role)"


def test_serialize_match_ping_target_values() -> None:
    assert HighlightBot.serialize_match_ping_target("none") == "none"
    assert HighlightBot.serialize_match_ping_target("here") == "here"
    assert HighlightBot.serialize_match_ping_target("role", 42) == "role:42"

    with pytest.raises(ValidationError):
        HighlightBot.serialize_match_ping_target("role")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stored_value", "role_map", "expected_content", "expected_everyone", "expected_roles"),
    [
        (None, {}, "@here", True, False),
        ("", {}, "@here", True, False),
        ("none", {}, None, False, False),
        ("here", {}, "@here", True, False),
        ("role:42", {42: DummyRole(id=42, mention="<@&42>")}, "<@&42>", False, True),
    ],
)
async def test_resolve_match_ping_announcement_supports_configured_targets(
    stored_value: str | None,
    role_map: dict[int, DummyRole],
    expected_content: str | None,
    expected_everyone: bool,
    expected_roles: bool,
) -> None:
    bot = _make_bot(_make_settings(apostado=stored_value))
    content, allowed_mentions = await HighlightBot.resolve_match_ping_announcement(
        bot,
        DummyGuild(role_map),
        _make_snapshot(ruleset=RulesetKey.APOSTADO),
    )

    assert content == expected_content
    assert allowed_mentions.everyone is expected_everyone
    assert allowed_mentions.roles is expected_roles
    assert bot.logger.warnings == []


@pytest.mark.asyncio
async def test_resolve_match_ping_announcement_falls_back_to_no_ping_for_missing_role() -> None:
    bot = _make_bot(_make_settings(apostado="role:999"))
    snapshot = _make_snapshot(ruleset=RulesetKey.APOSTADO)
    content, allowed_mentions = await HighlightBot.resolve_match_ping_announcement(
        bot,
        DummyGuild(),
        snapshot,
    )

    assert content is None
    assert allowed_mentions.everyone is False
    assert allowed_mentions.roles is False
    assert bot.logger.warnings == [
        (
            "match_ping_role_unavailable",
            {
                "guild_id": 98765,
                "match_id": str(snapshot.match.id),
                "ruleset": "apostado",
                "raw_target": "role:999",
            },
        )
    ]


def test_latest_update_embed_mentions_configured_match_ping() -> None:
    bot = object.__new__(HighlightBot)
    embed = HighlightBot.build_latest_update_embed(bot, "!")
    rendered_text = "\n".join(field.value for field in embed.fields)

    assert "configured match ping" in rendered_text
    assert "pings `@here`" not in rendered_text


def test_match_ping_command_source_and_status_rendering_are_registered() -> None:
    source = inspect.getsource(HighlightBot._register_app_commands)

    assert '@admin_group.command(name="set-apostado-match-ping"' in source
    assert '@admin_group.command(name="set-highlight-match-ping"' in source
    assert '@admin_group.command(name="set-esport-match-ping"' in source
    assert "MATCH_PING_TARGET_CHOICES" in source
    assert "set_match_ping_target(" in source
    assert "is_admin_member" in source
    assert "Apostado match ping:" in source
    assert "Highlight match ping:" in source
    assert "Esport match ping:" in source
    assert "ephemeral=True" in source


def test_announce_match_created_uses_resolved_ping_target() -> None:
    source = inspect.getsource(HighlightBot.announce_match_created)

    assert 'content="@here"' not in source
    assert "resolve_match_ping_announcement" in source
