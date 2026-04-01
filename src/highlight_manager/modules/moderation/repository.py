from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.moderation import AuditLogModel, ModerationActionModel


class ModerationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_audit(self, **kwargs) -> AuditLogModel:
        audit = AuditLogModel(**kwargs)
        self.session.add(audit)
        await self.session.flush()
        return audit

    async def create_action(self, **kwargs) -> ModerationActionModel:
        action = ModerationActionModel(**kwargs)
        self.session.add(action)
        await self.session.flush()
        return action
