from __future__ import annotations

from highlight_manager.modules.common.enums import AuditAction, AuditEntityType, ModerationActionType
from highlight_manager.modules.moderation.repository import ModerationRepository


class ModerationService:
    async def audit(
        self,
        repository: ModerationRepository,
        *,
        guild_id: int,
        action: AuditAction,
        entity_type: AuditEntityType,
        entity_id: str | None,
        actor_player_id: int | None = None,
        target_player_id: int | None = None,
        reason: str | None = None,
        metadata_json: dict | None = None,
    ):
        return await repository.create_audit(
            guild_id=guild_id,
            actor_player_id=actor_player_id,
            target_player_id=target_player_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            reason=reason,
            metadata_json=metadata_json,
        )

    async def apply_action(
        self,
        repository: ModerationRepository,
        *,
        guild_id: int,
        player_id: int,
        action_type: ModerationActionType,
        actor_player_id: int | None,
        reason: str,
        related_match_id=None,
        expires_at=None,
    ):
        return await repository.create_action(
            guild_id=guild_id,
            player_id=player_id,
            action_type=action_type,
            actor_player_id=actor_player_id,
            reason=reason,
            related_match_id=related_match_id,
            expires_at=expires_at,
        )
