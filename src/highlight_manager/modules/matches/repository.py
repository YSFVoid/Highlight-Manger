from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from highlight_manager.db.models.competitive import MatchModel, MatchPlayerModel, MatchVoteModel, QueueModel, QueuePlayerModel
from highlight_manager.db.models.core import PlayerModel
from highlight_manager.modules.common.enums import MatchResultPhase, MatchState, QueueState
from highlight_manager.modules.common.time import utcnow
from highlight_manager.modules.matches.types import MatchSnapshot, QueueSnapshot


ACTIVE_QUEUE_STATES = [
    QueueState.QUEUE_OPEN,
    QueueState.FILLING,
    QueueState.READY_CHECK,
    QueueState.FULL_PENDING_ROOM_INFO,
]
ACTIVE_MATCH_STATES = [
    MatchState.CREATED,
    MatchState.MOVING,
    MatchState.LIVE,
    MatchState.RESULT_PENDING,
    MatchState.EXPIRED,
]


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
        lookup = await self.get_player_discord_ids([row.player_id for row in players])
        ready_player_ids = {row.player_id for row in players if row.ready_at is not None}
        return QueueSnapshot(
            queue=queue,
            players=players,
            player_discord_ids=lookup,
            ready_player_ids=ready_player_ids,
        )

    async def get_active_queue_for_playlist(self, guild_id: int, ruleset_key, mode) -> QueueModel | None:
        return await self.session.scalar(
            select(QueueModel)
            .where(
                QueueModel.guild_id == guild_id,
                QueueModel.ruleset_key == ruleset_key,
                QueueModel.mode == mode,
                QueueModel.state.in_(ACTIVE_QUEUE_STATES),
            )
            .order_by(QueueModel.created_at.asc(), QueueModel.id.asc())
        )

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

    async def mark_queue_player_ready(self, queue_id: UUID, player_id: int) -> QueuePlayerModel | None:
        player = await self.get_queue_player(queue_id, player_id)
        if player is None:
            return None
        if player.ready_at is None:
            player.ready_at = utcnow()
            await self.session.flush()
        return player

    async def clear_queue_ready_state(self, queue_id: UUID) -> None:
        for player in await self.list_queue_players(queue_id):
            player.ready_at = None
        await self.session.flush()

    async def set_queue_creator(self, queue_id: UUID, creator_player_id: int) -> QueueModel | None:
        queue = await self.get_queue(queue_id, for_update=True)
        if queue is None:
            return None
        queue.creator_player_id = creator_player_id
        await self.session.flush()
        return queue

    async def delete_queue_player(self, row: QueuePlayerModel) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def next_match_number(self, guild_id: int) -> int:
        value = await self.session.scalar(select(func.max(MatchModel.match_number)).where(MatchModel.guild_id == guild_id))
        return int(value or 0) + 1

    async def create_match_from_queue(self, snapshot: QueueSnapshot, *, result_deadline_at: datetime) -> MatchSnapshot:
        team1_captain_player_id = (
            snapshot.queue.creator_player_id
            if snapshot.queue.creator_player_id in snapshot.team1_ids
            else snapshot.team1_ids[0]
            if snapshot.team1_ids
            else None
        )
        team2_captain_player_id = (
            snapshot.queue.creator_player_id
            if snapshot.queue.creator_player_id in snapshot.team2_ids
            else snapshot.team2_ids[0]
            if snapshot.team2_ids
            else None
        )
        match = MatchModel(
            guild_id=snapshot.queue.guild_id,
            season_id=snapshot.queue.season_id,
            queue_id=snapshot.queue.id,
            match_number=await self.next_match_number(snapshot.queue.guild_id),
            creator_player_id=snapshot.queue.creator_player_id,
            team1_captain_player_id=team1_captain_player_id,
            team2_captain_player_id=team2_captain_player_id,
            ruleset_key=snapshot.queue.ruleset_key,
            mode=snapshot.queue.mode,
            result_phase=MatchResultPhase.CAPTAIN,
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

    async def list_due_ready_check_timeouts(self, now: datetime) -> list[QueueModel]:
        result = await self.session.scalars(
            select(QueueModel).where(
                QueueModel.state == QueueState.READY_CHECK,
                QueueModel.room_info_deadline_at.is_not(None),
                QueueModel.room_info_deadline_at <= now,
            )
        )
        return list(result.all())

    async def list_stale_queue_timeout_candidates(self) -> list[QueueModel]:
        result = await self.session.scalars(
            select(QueueModel)
            .where(QueueModel.state.in_([QueueState.QUEUE_OPEN, QueueState.FILLING]))
            .order_by(QueueModel.created_at.asc(), QueueModel.id.asc())
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

    async def list_recent_confirmed_rematch_candidates(
        self,
        *,
        guild_id: int,
        season_id: int,
        ruleset_key,
        mode,
        match_id: UUID,
        confirmed_after: datetime,
        now: datetime,
    ) -> list[MatchModel]:
        result = await self.session.scalars(
            select(MatchModel)
            .where(
                MatchModel.guild_id == guild_id,
                MatchModel.season_id == season_id,
                MatchModel.ruleset_key == ruleset_key,
                MatchModel.mode == mode,
                MatchModel.state == MatchState.CONFIRMED,
                MatchModel.confirmed_at.is_not(None),
                MatchModel.confirmed_at >= confirmed_after,
                MatchModel.confirmed_at < now,
                MatchModel.id != match_id,
            )
            .order_by(MatchModel.confirmed_at.asc(), MatchModel.match_number.asc())
        )
        return list(result.all())

    async def list_review_inbox_candidates(
        self,
        guild_id: int,
        *,
        now: datetime,
        limit: int | None,
    ) -> list[MatchModel]:
        has_active_vote = exists().where(
            MatchVoteModel.match_id == MatchModel.id,
            MatchVoteModel.superseded_at.is_(None),
        )
        result_due = and_(
            MatchModel.result_deadline_at.is_not(None),
            MatchModel.result_deadline_at <= now,
        )
        captain_due = and_(
            MatchModel.captain_deadline_at.is_not(None),
            MatchModel.captain_deadline_at <= now,
        )
        fallback_due = and_(
            MatchModel.fallback_deadline_at.is_not(None),
            MatchModel.fallback_deadline_at <= now,
        )
        stmt = (
            select(MatchModel)
            .where(
                MatchModel.guild_id == guild_id,
                MatchModel.state.in_([MatchState.LIVE, MatchState.RESULT_PENDING, MatchState.EXPIRED]),
                or_(
                    MatchModel.state == MatchState.EXPIRED,
                    MatchModel.result_phase == MatchResultPhase.STAFF_REVIEW,
                    result_due,
                    captain_due,
                    fallback_due,
                    has_active_vote,
                ),
            )
            .order_by(MatchModel.created_at.asc(), MatchModel.match_number.asc())
        )
        if limit is not None:
            stmt = stmt.limit(max(limit, 1))
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def list_due_captain_timeouts(self, now: datetime) -> list[MatchModel]:
        result = await self.session.scalars(
            select(MatchModel).where(
                MatchModel.state.in_([MatchState.LIVE, MatchState.RESULT_PENDING]),
                MatchModel.result_phase == MatchResultPhase.CAPTAIN,
                MatchModel.captain_deadline_at.is_not(None),
                MatchModel.captain_deadline_at <= now,
            )
        )
        return list(result.all())

    async def list_due_fallback_timeouts(self, now: datetime) -> list[MatchModel]:
        result = await self.session.scalars(
            select(MatchModel).where(
                MatchModel.state.in_([MatchState.LIVE, MatchState.RESULT_PENDING]),
                MatchModel.result_phase == MatchResultPhase.FALLBACK,
                MatchModel.fallback_deadline_at.is_not(None),
                MatchModel.fallback_deadline_at <= now,
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
                QueueModel.state.in_(ACTIVE_QUEUE_STATES)
            )
        )
        return list(result.all())

    async def list_active_queue_ids_for_guild(self, guild_id: int) -> list[UUID]:
        result = await self.session.scalars(
            select(QueueModel.id).where(
                QueueModel.guild_id == guild_id,
                QueueModel.state.in_(ACTIVE_QUEUE_STATES),
            )
        )
        return list(result.all())

    async def count_active_queues_by_state(self, guild_id: int) -> dict[QueueState, int]:
        result = await self.session.execute(
            select(QueueModel.state, func.count())
            .where(
                QueueModel.guild_id == guild_id,
                QueueModel.state.in_(ACTIVE_QUEUE_STATES),
            )
            .group_by(QueueModel.state)
        )
        return {state: int(count) for state, count in result.all()}

    async def list_active_matches(self) -> list[MatchModel]:
        result = await self.session.scalars(
            select(MatchModel).where(
                MatchModel.state.in_(ACTIVE_MATCH_STATES)
            )
        )
        return list(result.all())

    async def list_active_matches_for_guild(self, guild_id: int) -> list[MatchModel]:
        result = await self.session.scalars(
            select(MatchModel).where(
                MatchModel.guild_id == guild_id,
                MatchModel.state.in_(ACTIVE_MATCH_STATES),
            )
        )
        return list(result.all())

    async def count_active_matches_by_state(self, guild_id: int) -> dict[MatchState, int]:
        result = await self.session.execute(
            select(MatchModel.state, func.count())
            .where(
                MatchModel.guild_id == guild_id,
                MatchModel.state.in_(ACTIVE_MATCH_STATES),
            )
            .group_by(MatchModel.state)
        )
        return {state: int(count) for state, count in result.all()}

    async def count_due_room_info_reminders(self, guild_id: int, threshold: datetime) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(QueueModel)
            .where(
                QueueModel.guild_id == guild_id,
                QueueModel.state == QueueState.FULL_PENDING_ROOM_INFO,
                QueueModel.room_info_deadline_at.is_not(None),
                QueueModel.room_info_reminder_sent_at.is_(None),
                QueueModel.room_info_deadline_at <= threshold,
            )
        )
        return int(value or 0)

    async def count_due_room_info_timeouts(self, guild_id: int, now: datetime) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(QueueModel)
            .where(
                QueueModel.guild_id == guild_id,
                QueueModel.state == QueueState.FULL_PENDING_ROOM_INFO,
                QueueModel.room_info_deadline_at <= now,
            )
        )
        return int(value or 0)

    async def count_due_captain_timeouts(self, guild_id: int, now: datetime) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(MatchModel)
            .where(
                MatchModel.guild_id == guild_id,
                MatchModel.state.in_([MatchState.LIVE, MatchState.RESULT_PENDING]),
                MatchModel.result_phase == MatchResultPhase.CAPTAIN,
                MatchModel.captain_deadline_at.is_not(None),
                MatchModel.captain_deadline_at <= now,
            )
        )
        return int(value or 0)

    async def count_due_fallback_timeouts(self, guild_id: int, now: datetime) -> int:
        value = await self.session.scalar(
            select(func.count())
            .select_from(MatchModel)
            .where(
                MatchModel.guild_id == guild_id,
                MatchModel.state.in_([MatchState.LIVE, MatchState.RESULT_PENDING]),
                MatchModel.result_phase == MatchResultPhase.FALLBACK,
                MatchModel.fallback_deadline_at.is_not(None),
                MatchModel.fallback_deadline_at <= now,
            )
        )
        return int(value or 0)

    async def get_match_by_number(self, guild_id: int, match_number: int) -> MatchModel | None:
        return await self.session.scalar(
            select(MatchModel).where(
                MatchModel.guild_id == guild_id,
                MatchModel.match_number == match_number,
            )
        )

    async def update_match_room_info(
        self,
        match: MatchModel,
        *,
        room_code: str,
        room_password: str,
        room_notes: str | None,
    ) -> None:
        match.room_code = room_code
        match.room_password = room_password
        match.room_notes = room_notes
        match.rehost_count += 1
        await self.session.flush()

    async def _player_lookup(self, player_ids: list[int]) -> dict[int, int]:
        if not player_ids:
            return {}
        result = await self.session.scalars(select(PlayerModel).where(PlayerModel.id.in_(player_ids)))
        return {player.id: player.discord_user_id for player in result.all()}

    async def get_player_discord_ids(self, player_ids: list[int]) -> dict[int, int]:
        return await self._player_lookup(player_ids)
