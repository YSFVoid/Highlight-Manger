from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.moderation import AuditLogModel, ModerationActionModel
from highlight_manager.modules.common.enums import AuditAction, AuditEntityType


class ModerationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_audit(self, **kwargs) -> AuditLogModel:
        audit = AuditLogModel(**kwargs)
        self.session.add(audit)
        await self.session.flush()
        return audit

    async def list_match_rehost_audits(self, match_id: UUID, *, limit: int | None = 10) -> list[AuditLogModel]:
        stmt = (
            select(AuditLogModel)
            .where(
                AuditLogModel.entity_type == AuditEntityType.MATCH,
                AuditLogModel.entity_id == str(match_id),
                AuditLogModel.action == AuditAction.MATCH_REHOSTED,
            )
            .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
        )
        if limit is not None:
            stmt = stmt.limit(max(limit, 1))
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def get_match_anti_rematch_audit(self, match_id: UUID) -> AuditLogModel | None:
        return await self.session.scalar(
            select(AuditLogModel)
            .where(
                AuditLogModel.entity_type == AuditEntityType.MATCH,
                AuditLogModel.entity_id == str(match_id),
                AuditLogModel.action == AuditAction.MATCH_ANTI_REMATCH_FLAGGED,
            )
            .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
        )

    async def list_phase4_evidence_audits(self, guild_id: int, *, limit: int = 10) -> list[AuditLogModel]:
        stmt = (
            select(AuditLogModel)
            .where(
                AuditLogModel.guild_id == guild_id,
                AuditLogModel.entity_type == AuditEntityType.GUILD,
                AuditLogModel.action == AuditAction.PHASE4_EVIDENCE_RECORDED,
            )
            .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
            .limit(max(limit, 1))
        )
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def create_action(self, **kwargs) -> ModerationActionModel:
        action = ModerationActionModel(**kwargs)
        self.session.add(action)
        await self.session.flush()
        return action
