from __future__ import annotations

from datetime import datetime
from typing import Iterable
from uuid import UUID

from highlight_manager.db.models.core import PlayerModel
from highlight_manager.modules.common.enums import ActivityKind
from highlight_manager.modules.common.exceptions import ValidationError
from highlight_manager.modules.profiles.repository import ProfileRepository


class ProfileService:
    async def ensure_player(
        self,
        repository: ProfileRepository,
        guild_id: int,
        discord_user_id: int,
        *,
        display_name: str | None = None,
        global_name: str | None = None,
        joined_guild_at: datetime | None = None,
    ) -> PlayerModel:
        return await repository.ensure_player(
            guild_id,
            discord_user_id,
            display_name=display_name,
            global_name=global_name,
            joined_guild_at=joined_guild_at,
        )

    async def require_not_blacklisted(self, repository: ProfileRepository, guild_id: int, discord_user_id: int) -> PlayerModel:
        player = await repository.get_player(guild_id, discord_user_id)
        if player is None:
            player = await repository.ensure_player(guild_id, discord_user_id)
        if player.is_blacklisted:
            raise ValidationError("You are blacklisted from competitive participation.")
        return player

    async def require_idle(self, repository: ProfileRepository, player: PlayerModel) -> None:
        activity = await repository.ensure_activity(player.id)
        if activity.activity_kind != ActivityKind.IDLE:
            raise ValidationError("You are already in an active queue, match, or tournament.")

    async def set_blacklisted(self, repository: ProfileRepository, player_id: int, is_blacklisted: bool) -> PlayerModel:
        return await repository.set_blacklisted(player_id, is_blacklisted)

    async def set_queue_activity(self, repository: ProfileRepository, player_id: int, queue_id: UUID) -> None:
        await repository.set_activity(player_id, activity_kind=ActivityKind.QUEUE, queue_id=queue_id)

    async def set_match_activity(self, repository: ProfileRepository, player_id: int, match_id: UUID) -> None:
        await repository.set_activity(player_id, activity_kind=ActivityKind.MATCH, match_id=match_id)

    async def set_tournament_activity(self, repository: ProfileRepository, player_id: int, tournament_id: UUID) -> None:
        await repository.set_activity(player_id, activity_kind=ActivityKind.TOURNAMENT, tournament_id=tournament_id)

    async def clear_activity(self, repository: ProfileRepository, player_ids: Iterable[int]) -> None:
        for player_id in player_ids:
            await repository.set_activity(player_id, activity_kind=ActivityKind.IDLE)
