from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.core import PlayerActivityStateModel, PlayerModel
from highlight_manager.modules.common.enums import ActivityKind
from highlight_manager.modules.common.exceptions import NotFoundError
from highlight_manager.modules.common.time import utcnow


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_player(self, guild_id: int, discord_user_id: int) -> PlayerModel | None:
        return await self.session.scalar(
            select(PlayerModel).where(
                PlayerModel.guild_id == guild_id,
                PlayerModel.discord_user_id == discord_user_id,
            )
        )

    async def ensure_player(
        self,
        guild_id: int,
        discord_user_id: int,
        *,
        display_name: str | None = None,
        global_name: str | None = None,
        joined_guild_at: datetime | None = None,
    ) -> PlayerModel:
        player = await self.get_player(guild_id, discord_user_id)
        if player is None:
            player = PlayerModel(
                guild_id=guild_id,
                discord_user_id=discord_user_id,
                display_name=display_name,
                global_name=global_name,
                joined_guild_at=joined_guild_at,
            )
            self.session.add(player)
            await self.session.flush()
        else:
            player.display_name = display_name or player.display_name
            player.global_name = global_name or player.global_name
            if joined_guild_at is not None:
                player.joined_guild_at = joined_guild_at
        return player

    async def ensure_activity(self, player_id: int) -> PlayerActivityStateModel:
        activity = await self.session.get(PlayerActivityStateModel, player_id)
        if activity is None:
            activity = PlayerActivityStateModel(
                player_id=player_id,
                activity_kind=ActivityKind.IDLE,
                updated_at=utcnow(),
            )
            self.session.add(activity)
            await self.session.flush()
        return activity

    async def get_player_by_id(self, player_id: int) -> PlayerModel | None:
        return await self.session.get(PlayerModel, player_id)

    async def set_blacklisted(self, player_id: int, is_blacklisted: bool) -> PlayerModel:
        player = await self.get_player_by_id(player_id)
        if player is None:
            raise NotFoundError("Player not found.")
        player.is_blacklisted = is_blacklisted
        await self.session.flush()
        return player

    async def list_players_by_ids(self, player_ids: list[int]) -> list[PlayerModel]:
        if not player_ids:
            return []
        result = await self.session.scalars(
            select(PlayerModel).where(PlayerModel.id.in_(player_ids))
        )
        return list(result.all())

    async def list_players_by_discord_ids(self, guild_id: int, discord_user_ids: list[int]) -> list[PlayerModel]:
        if not discord_user_ids:
            return []
        result = await self.session.scalars(
            select(PlayerModel).where(
                PlayerModel.guild_id == guild_id,
                PlayerModel.discord_user_id.in_(discord_user_ids),
            )
        )
        return list(result.all())

    async def set_activity(
        self,
        player_id: int,
        *,
        activity_kind: ActivityKind,
        queue_id: UUID | None = None,
        match_id: UUID | None = None,
        tournament_id: UUID | None = None,
    ) -> PlayerActivityStateModel:
        activity = await self.ensure_activity(player_id)
        activity.activity_kind = activity_kind
        activity.queue_id = queue_id
        activity.match_id = match_id
        activity.tournament_id = tournament_id
        activity.updated_at = utcnow()
        await self.session.flush()
        return activity

    async def list_non_idle_activities(self) -> list[PlayerActivityStateModel]:
        result = await self.session.scalars(
            select(PlayerActivityStateModel).where(PlayerActivityStateModel.activity_kind != ActivityKind.IDLE)
        )
        return list(result.all())

    async def count_stale_activity_rows_for_guild(
        self,
        guild_id: int,
        *,
        active_queue_ids: set[UUID],
        active_match_ids: set[UUID],
    ) -> int:
        result = await self.session.scalars(
            select(PlayerActivityStateModel)
            .join(PlayerModel, PlayerModel.id == PlayerActivityStateModel.player_id)
            .where(
                PlayerModel.guild_id == guild_id,
                PlayerActivityStateModel.activity_kind != ActivityKind.IDLE,
            )
        )
        stale_count = 0
        for activity in result.all():
            if activity.queue_id is not None and activity.queue_id not in active_queue_ids:
                stale_count += 1
                continue
            if activity.match_id is not None and activity.match_id not in active_match_ids:
                stale_count += 1
        return stale_count

    async def set_activity_for_players(
        self,
        player_ids: list[int],
        *,
        activity_kind: ActivityKind,
        queue_id: UUID | None = None,
        match_id: UUID | None = None,
        tournament_id: UUID | None = None,
    ) -> list[PlayerActivityStateModel]:
        if not player_ids:
            return []
        unique_player_ids = list(dict.fromkeys(player_ids))
        existing_result = await self.session.scalars(
            select(PlayerActivityStateModel).where(PlayerActivityStateModel.player_id.in_(unique_player_ids))
        )
        activities_by_player_id = {activity.player_id: activity for activity in existing_result.all()}
        for player_id in unique_player_ids:
            if player_id in activities_by_player_id:
                continue
            activity = PlayerActivityStateModel(
                player_id=player_id,
                activity_kind=ActivityKind.IDLE,
                updated_at=utcnow(),
            )
            self.session.add(activity)
            activities_by_player_id[player_id] = activity
        await self.session.flush()
        activities = [activities_by_player_id[player_id] for player_id in unique_player_ids]
        now = utcnow()
        for activity in activities:
            activity.activity_kind = activity_kind
            activity.queue_id = queue_id
            activity.match_id = match_id
            activity.tournament_id = tournament_id
            activity.updated_at = now
        await self.session.flush()
        return activities
