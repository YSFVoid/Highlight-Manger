from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.competitive import MatchModel, MatchPlayerModel, MatchVoteModel, QueueModel, QueuePlayerModel
from highlight_manager.db.models.core import PlayerModel
from highlight_manager.modules.common.enums import MatchState, QueueState
from highlight_manager.modules.common.time import utcnow
from highlight_manager.modules.matches.types import MatchSnapshot, QueueSnapshot


class MatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_queue(
        self,
        *,
        guild_id: int,
        season_id: int,
        creator_player_id: int,
        ruleset_key,
        mode,
        team_size: int,
        source_channel_id: int | None,
    ) -> QueueSnapshot:
        queue = QueueModel(
            guild_id=guild_id,
            season_id=season_id,
            creator_player_id=creator_player_id,
            ruleset_key=ruleset_key,
            mode=mode,
            team_size=team_size,
            source_channel_id=source_channel_id,
        )
        self.session.add(queue)
        await self.session.flush()
        queue_player = QueuePlayerModel(queue_id=queue.id, player_id=creator_player_id, team_number=1)
        self.session.add(queue_player)
        await self.session.flush()
        player_lookup = await self._player_lookup([creator_player_id])
        return QueueSnapshot(queue=queue, players=[queue_player], player_discord_ids=player_lookup)

    async def get_queue(self, queue_id: UUID, *, for_update: bool = False) -> QueueModel | None:
        stmt = select(QueueModel).where(QueueModel.id == queue_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def list_queue_players(self, queue_id: UUID) -> list[QueuePlayerModel]:
        result = await self.session.scalars(
            select(QueuePlayerModel)
            .where(QueuePlayerModel.queue_id == queue_id)
            .order_by(QueuePlayerModel.joined_at.asc(), QueuePlayerModel.id.asc())
        )
        return list(result.all())

    async def get_queue_snapshot(self, queue_id: UUID, *, for_update: bool = False) -> QueueSnapshot | None:
        queue = await self.get_queue(queue_id, for_update=for_update)
        if queue is None:
            return None
        players = await self.list_queue_players(queue_id)
        lookup = await self._player_lookup([row.player_id for row in players])
        return QueueSnapshot(queue=queue, players=players, player_discord_ids=lookup)

    async def get_queue_player(self, queue_id: UUID, player_id: int) -> QueuePlayerModel | None:
        return await self.session.scalar(
            select(QueuePlayerModel).where(
                QueuePlayerModel.queue_id == queue_id,
                QueuePlayerModel.player_id == player_id,
            )
        )

    async def add_queue_player(self, queue_id: UUID, player_id: int, team_number: int) -> QueuePlayerModel:
        player = QueuePlayerModel(queue_id=queue_id, player_id=player_id, team_number=team_number)
        self.session.add(player)
        await self.session.flush()
        return player

    async def delete_queue_player(self, row: QueuePlayerModel) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def next_match_number(self, guild_id: int) -> int:
        value = await self.session.scalar(select(func.max(MatchModel.match_number)).where(MatchModel.guild_id == guild_id))
        return int(value or 0) + 1

    async def create_match_from_queue(self, snapshot: QueueSnapshot, *, result_deadline_at: datetime) -> MatchSnapshot:
        match = MatchModel(
            guild_id=snapshot.queue.guild_id,
            season_id=snapshot.queue.season_id,
            queue_id=snapshot.queue.id,
            match_number=await self.next_match_number(snapshot.queue.guild_id),
            creator_player_id=snapshot.queue.creator_player_id,
            ruleset_key=snapshot.queue.ruleset_key,
            mode=snapshot.queue.mode,
            team_size=snapshot.queue.team_size,
            room_code=snapshot.queue.room_code,
            room_password=snapshot.queue.room_password,
            room_notes=snapshot.queue.room_notes,
            source_channel_id=snapshot.queue.source_channel_id,
            public_message_id=snapshot.queue.public_message_id,
            result_deadline_at=result_deadline_at,
            room_info_submitted_by_player_id=snapshot.queue.room_info_submitted_by_player_id,
        )
        self.session.add(match)
        await self.session.flush()
        players: list[MatchPlayerModel] = []
        for queue_player in snapshot.players:
            row = MatchPlayerModel(match_id=match.id, player_id=queue_player.player_id, team_number=queue_player.team_number)
            self.session.add(row)
            players.append(row)
        await self.session.flush()
        lookup = await self._player_lookup([row.player_id for row in players])
        return MatchSnapshot(match=match, players=players, votes=[], player_discord_ids=lookup)

    async def get_match(self, match_id: UUID, *, for_update: bool = False) -> MatchModel | None:
        stmt = select(MatchModel).where(MatchModel.id == match_id)
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    async def get_match_snapshot(self, match_id: UUID, *, for_update: bool = False) -> MatchSnapshot | None:
        match = await self.get_match(match_id, for_update=for_update)
        if match is None:
            return None
        player_result = await self.session.scalars(
            select(MatchPlayerModel)
            .where(MatchPlayerModel.match_id == match_id)
            .order_by(MatchPlayerModel.team_number.asc(), MatchPlayerModel.id.asc())
        )
        vote_result = await self.session.scalars(
            select(MatchVoteModel)
            .where(MatchVoteModel.match_id == match_id, MatchVoteModel.superseded_at.is_(None))
            .order_by(MatchVoteModel.created_at.asc(), MatchVoteModel.id.asc())
        )
        players = list(player_result.all())
        votes = list(vote_result.all())
        lookup = await self._player_lookup([row.player_id for row in players])
        return MatchSnapshot(match=match, players=players, votes=votes, player_discord_ids=lookup)

    async def supersede_active_vote(self, match_id: UUID, player_id: int) -> None:
        result = await self.session.scalars(
            select(MatchVoteModel).where(
                MatchVoteModel.match_id == match_id,
                MatchVoteModel.player_id == player_id,
                MatchVoteModel.superseded_at.is_(None),
            )
        )
        now = utcnow()
        for vote in result.all():
            vote.superseded_at = now
        await self.session.flush()

    async def create_vote(
        self,
        *,
        match_id: UUID,
        player_id: int,
        winner_team_number: int,
        winner_mvp_player_id: int | None,
        loser_mvp_player_id: int | None,
    ) -> MatchVoteModel:
        vote = MatchVoteModel(
            match_id=match_id,
            player_id=player_id,
            winner_team_number=winner_team_number,
            winner_mvp_player_id=winner_mvp_player_id,
            loser_mvp_player_id=loser_mvp_player_id,
        )
        self.session.add(vote)
        await self.session.flush()
        return vote

    async def list_due_room_info_timeouts(self, now: datetime) -> list[QueueModel]:
        result = await self.session.scalars(
            select(QueueModel).where(
                QueueModel.state == QueueState.FULL_PENDING_ROOM_INFO,
                QueueModel.room_info_deadline_at <= now,
            )
        )
        return list(result.all())

    async def list_due_room_info_reminders(self, threshold: datetime) -> list[QueueModel]:
        result = await self.session.scalars(
            select(QueueModel).where(
                QueueModel.state == QueueState.FULL_PENDING_ROOM_INFO,
                QueueModel.room_info_deadline_at.is_not(None),
                QueueModel.room_info_reminder_sent_at.is_(None),
                QueueModel.room_info_deadline_at <= threshold,
            )
        )
        return list(result.all())

    async def list_due_result_timeouts(self, now: datetime) -> list[MatchModel]:
        result = await self.session.scalars(
            select(MatchModel).where(
                MatchModel.state.in_([MatchState.LIVE, MatchState.RESULT_PENDING]),
                MatchModel.result_deadline_at <= now,
            )
        )
        return list(result.all())

    async def set_queue_public_message_id(self, queue_id: UUID, public_message_id: int) -> None:
        queue = await self.get_queue(queue_id, for_update=True)
        if queue is None:
            return
        queue.public_message_id = public_message_id
        await self.session.flush()

    async def list_active_queues(self) -> list[QueueModel]:
        result = await self.session.scalars(
            select(QueueModel).where(
                QueueModel.state.in_(
                    [QueueState.QUEUE_OPEN, QueueState.FILLING, QueueState.FULL_PENDING_ROOM_INFO]
                )
            )
        )
        return list(result.all())

    async def list_active_matches(self) -> list[MatchModel]:
        result = await self.session.scalars(
            select(MatchModel).where(
                MatchModel.state.in_(
                    [MatchState.CREATED, MatchState.MOVING, MatchState.LIVE, MatchState.RESULT_PENDING, MatchState.EXPIRED]
                )
            )
        )
        return list(result.all())

    async def get_match_by_number(self, guild_id: int, match_number: int) -> MatchModel | None:
        return await self.session.scalar(
            select(MatchModel).where(
                MatchModel.guild_id == guild_id,
                MatchModel.match_number == match_number,
            )
        )

    async def _player_lookup(self, player_ids: list[int]) -> dict[int, int]:
        if not player_ids:
            return {}
        result = await self.session.scalars(select(PlayerModel).where(PlayerModel.id.in_(player_ids)))
        return {player.id: player.discord_user_id for player in result.all()}
