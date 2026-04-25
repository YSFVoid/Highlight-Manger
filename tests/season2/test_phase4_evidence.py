from __future__ import annotations

import inspect

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import highlight_manager.db.models  # noqa: F401
from highlight_manager.app.bot import HighlightBot
from highlight_manager.app.config import Settings
from highlight_manager.db.base import Base
from highlight_manager.db.session import create_engine, create_session_factory
from highlight_manager.modules.common.enums import AuditAction, AuditEntityType
from highlight_manager.modules.guilds.repository import GuildRepository
from highlight_manager.modules.guilds.service import GuildService
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.phase4.ui import build_phase4_evidence_embed


@pytest.fixture()
async def session(tmp_path) -> AsyncSession:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'phase4-evidence.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _ensure_guild(session: AsyncSession, discord_guild_id: int) -> int:
    settings = Settings(DISCORD_TOKEN="token", DATABASE_URL="sqlite+aiosqlite:///test.db")
    bundle = await GuildService(settings).ensure_guild(GuildRepository(session), discord_guild_id, "Highlight")
    return bundle.guild.id


@pytest.mark.asyncio
async def test_phase4_evidence_audits_are_listed_for_one_guild(session: AsyncSession) -> None:
    guild_id = await _ensure_guild(session, 91001)
    other_guild_id = await _ensure_guild(session, 91002)
    moderation = ModerationRepository(session)

    kept = await moderation.create_audit(
        guild_id=guild_id,
        entity_type=AuditEntityType.GUILD,
        entity_id=str(guild_id),
        action=AuditAction.PHASE4_EVIDENCE_RECORDED,
        reason="Players keep missing the ready-check deadline.",
        metadata_json={
            "area": "queue",
            "source": "staff_feedback",
            "frequency": "repeated",
            "impact": "medium",
            "trust_risk": "low",
            "recommended_action": "fix_soon",
            "evidence": "Three staff notes from the same evening.",
        },
    )
    await moderation.create_audit(
        guild_id=other_guild_id,
        entity_type=AuditEntityType.GUILD,
        entity_id=str(other_guild_id),
        action=AuditAction.PHASE4_EVIDENCE_RECORDED,
        reason="Other guild evidence",
    )
    await moderation.create_audit(
        guild_id=guild_id,
        entity_type=AuditEntityType.GUILD,
        entity_id=str(guild_id),
        action=AuditAction.QUEUE_CANCELLED,
        reason="Not Phase 4 evidence",
    )

    audits = await moderation.list_phase4_evidence_audits(guild_id)

    assert [audit.id for audit in audits] == [kept.id]
    assert audits[0].metadata_json["area"] == "queue"
    assert audits[0].metadata_json["recommended_action"] == "fix_soon"


@pytest.mark.asyncio
async def test_phase4_evidence_embed_renders_empty_and_populated_states(session: AsyncSession) -> None:
    empty = build_phase4_evidence_embed([])
    assert empty.title == "Phase 4 Evidence Log"
    assert "No evidence recorded" in empty.fields[0].name

    guild_id = await _ensure_guild(session, 91003)
    moderation = ModerationRepository(session)
    audit = await moderation.create_audit(
        guild_id=guild_id,
        entity_type=AuditEntityType.GUILD,
        entity_id=str(guild_id),
        action=AuditAction.PHASE4_EVIDENCE_RECORDED,
        reason="Staff need a faster way to review held matches.",
        metadata_json={
            "area": "staff_ops",
            "frequency": "repeated",
            "impact": "high",
            "recommended_action": "phase4_candidate",
            "evidence": "Review inbox was checked after every match dispute.",
        },
    )

    populated = build_phase4_evidence_embed([audit])
    rendered = "\n".join(field.value for field in populated.fields)

    assert "staff_ops" in rendered
    assert "high" in rendered
    assert "repeated" in rendered
    assert "phase4_candidate" in rendered
    assert "Staff need a faster way" in rendered


def test_phase4_evidence_admin_commands_are_registered() -> None:
    source = inspect.getsource(HighlightBot._register_app_commands)

    assert '@admin_group.command(name="record-phase4-evidence"' in source
    assert '@admin_group.command(name="phase4-evidence"' in source
    assert "PHASE4_EVIDENCE_AREA_CHOICES" in source
    assert "PHASE4_EVIDENCE_SOURCE_CHOICES" in source
    assert "PHASE4_EVIDENCE_FREQUENCY_CHOICES" in source
    assert "PHASE4_EVIDENCE_IMPACT_CHOICES" in source
    assert "PHASE4_EVIDENCE_ACTION_CHOICES" in source
    assert "is_admin_member" in source
    assert "AuditAction.PHASE4_EVIDENCE_RECORDED" in source
    assert "list_phase4_evidence_audits" in source
    assert "build_phase4_evidence_embed" in source
    assert "ephemeral=True" in source
