from __future__ import annotations

from uuid import UUID

from highlight_manager.app.config import Settings
from highlight_manager.modules.common.enums import AuditAction, AuditEntityType, MatchPlayerResult, MatchState, QueueState
from highlight_manager.modules.common.exceptions import NotFoundError, StateTransitionError, ValidationError
from highlight_manager.modules.common.time import seconds_from_now, utcnow
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.states import MATCH_RESULT_OPEN_STATES, QUEUE_JOINABLE_STATES, QUEUE_MUTABLE_STATES
from highlight_manager.modules.matches.types import MatchSnapshot, QueueSnapshot
from highlight_manager.modules.matches.validators import validate_team_number
from highlight_manager.modules.moderation.repository import ModerationRepository
from highlight_manager.modules.moderation.service import ModerationService
from highlight_manager.modules.profiles.repository import ProfileRepository
from highlight_manager.modules.profiles.service import ProfileService
from highlight_manager.modules.ranks.repository import RankRepository
from highlight_manager.modules.ranks.service import RankService
from highlight_manager.modules.seasons.repository import SeasonRepository
from highlight_manager.modules.seasons.service import SeasonService


class MatchService:
    def __init__(
        self,
        settings: Settings,
        *,
        profile_service: ProfileService,
        season_service: SeasonService,
        rank_service: RankService,
        economy_service: EconomyService,
        moderation_service: ModerationService,
    ) -> None:
        self.settings = settings
        self.profile_service = profile_service
        self.season_service = season_service
        self.rank_service = rank_service
        self.economy_service = economy_service
        self.moderation_service = moderation_service

    @staticmethod
    def validate_result_payload(
        snapshot: MatchSnapshot,
        *,
        winner_team_number: int,
        winner_mvp_player_id: int | None,
        loser_mvp_player_id: int | None,
    ) -> None:
        validate_team_number(winner_team_number)
        winner_ids = set(snapshot.team1_ids if winner_team_number == 1 else snapshot.team2_ids)
        loser_ids = set(snapshot.team2_ids if winner_team_number == 1 else snapshot.team1_ids)
        if winner_mvp_player_id is not None and winner_mvp_player_id not in winner_ids:
            raise ValidationError("Winner MVP must be from the winning team.")
        if loser_mvp_player_id is not None and loser_mvp_player_id not in loser_ids:
            raise ValidationError("Loser MVP must be from the losing team.")
        if winner_mvp_player_id is not None and winner_mvp_player_id == loser_mvp_player_id:
            raise ValidationError("Winner MVP and loser MVP must be different players.")

    async def create_queue(
        self,
        repository: MatchRepository,
        profile_repository: ProfileRepository,
        moderation_repository: ModerationRepository,
        *,
        guild_id: int,
        season_id: int,
        creator_player_id: int,
        ruleset_key,
        mode,
        source_channel_id: int | None,
    ) -> QueueSnapshot:
        snapshot = await repository.create_queue(
            guild_id=guild_id,
            season_id=season_id,
            creator_player_id=creator_player_id,
            ruleset_key=ruleset_key,
            mode=mode,
            team_size=mode.team_size,
            source_channel_id=source_channel_id,
        )
        await self.profile_service.set_queue_activity(profile_repository, creator_player_id, snapshot.queue.id)
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=guild_id,
            action=AuditAction.QUEUE_CREATED,
            entity_type=AuditEntityType.QUEUE,
            entity_id=str(snapshot.queue.id),
            actor_player_id=creator_player_id,
        )
        return snapshot

    async def join_queue(
        self,
        repository: MatchRepository,
        profile_repository: ProfileRepository,
        moderation_repository: ModerationRepository,
        *,
        queue_id: UUID,
        player_id: int,
        team_number: int,
    ) -> QueueSnapshot:
        validate_team_number(team_number)
        snapshot = await repository.get_queue_snapshot(queue_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Queue not found.")
        if snapshot.queue.state not in QUEUE_JOINABLE_STATES:
            raise StateTransitionError("That queue is no longer joinable.")
        if any(row.player_id == player_id for row in snapshot.players):
            raise ValidationError("You are already in this queue.")
        team_count = sum(1 for row in snapshot.players if row.team_number == team_number)
        if team_count >= snapshot.queue.team_size:
            raise ValidationError(f"Team {team_number} is already full.")

        await repository.add_queue_player(queue_id, player_id, team_number)
        await self.profile_service.set_queue_activity(profile_repository, player_id, queue_id)
        snapshot = await repository.get_queue_snapshot(queue_id, for_update=True)
        assert snapshot is not None
        if snapshot.is_full:
            snapshot.queue.state = QueueState.FULL_PENDING_ROOM_INFO
            snapshot.queue.full_at = utcnow()
            snapshot.queue.room_info_deadline_at = seconds_from_now(self.settings.room_info_timeout_seconds)
        else:
            snapshot.queue.state = QueueState.FILLING
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.queue.guild_id,
            action=AuditAction.QUEUE_JOINED,
            entity_type=AuditEntityType.QUEUE,
            entity_id=str(queue_id),
            actor_player_id=player_id,
            metadata_json={"team_number": team_number},
        )
        return snapshot

    async def cancel_queue(
        self,
        repository: MatchRepository,
        profile_repository: ProfileRepository,
        moderation_repository: ModerationRepository,
        *,
        queue_id: UUID,
        actor_player_id: int | None,
        reason: str,
    ) -> QueueSnapshot:
        snapshot = await repository.get_queue_snapshot(queue_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Queue not found.")
        if snapshot.queue.state not in QUEUE_MUTABLE_STATES:
            raise StateTransitionError("That queue is already closed.")
        snapshot.queue.state = QueueState.QUEUE_CANCELLED
        snapshot.queue.cancel_reason = reason
        snapshot.queue.cancelled_at = utcnow()
        await self.profile_service.clear_activity(profile_repository, [row.player_id for row in snapshot.players])
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.queue.guild_id,
            action=AuditAction.QUEUE_CANCELLED,
            entity_type=AuditEntityType.QUEUE,
            entity_id=str(queue_id),
            actor_player_id=actor_player_id,
            reason=reason,
        )
        return snapshot

    async def leave_queue(
        self,
        repository: MatchRepository,
        profile_repository: ProfileRepository,
        moderation_repository: ModerationRepository,
        *,
        queue_id: UUID,
        player_id: int,
        reason: str = "Player left queue.",
    ) -> QueueSnapshot:
        snapshot = await repository.get_queue_snapshot(queue_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Queue not found.")
        row = await repository.get_queue_player(queue_id, player_id)
        if row is None:
            raise ValidationError("You are not in that queue.")
        await repository.delete_queue_player(row)
        await self.profile_service.clear_activity(profile_repository, [player_id])
        snapshot = await repository.get_queue_snapshot(queue_id, for_update=True)
        assert snapshot is not None
        if player_id == snapshot.queue.creator_player_id or snapshot.queue.state == QueueState.FULL_PENDING_ROOM_INFO:
            return await self.cancel_queue(
                repository,
                profile_repository,
                moderation_repository,
                queue_id=queue_id,
                actor_player_id=player_id,
                reason=reason,
            )
        snapshot.queue.state = QueueState.FILLING if snapshot.players else QueueState.QUEUE_CANCELLED
        if not snapshot.players:
            snapshot.queue.cancel_reason = "empty_queue"
            snapshot.queue.cancelled_at = utcnow()
        return snapshot

    async def submit_room_info(
        self,
        repository: MatchRepository,
        profile_repository: ProfileRepository,
        moderation_repository: ModerationRepository,
        *,
        queue_id: UUID,
        submitter_player_id: int,
        is_moderator: bool,
        room_code: str,
        room_password: str | None,
        room_notes: str | None,
    ) -> MatchSnapshot:
        snapshot = await repository.get_queue_snapshot(queue_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Queue not found.")
        if snapshot.queue.state != QueueState.FULL_PENDING_ROOM_INFO:
            raise StateTransitionError("That queue is not waiting for room info.")
        if submitter_player_id != snapshot.queue.creator_player_id and not is_moderator:
            raise ValidationError("Only the creator or staff can submit room info.")
        if not snapshot.is_full:
            raise ValidationError("The queue is no longer valid.")
        room_code = room_code.strip()
        if not room_code:
            raise ValidationError("Room ID is required before match creation.")
        room_password = (room_password or "").strip()
        if not room_password:
            raise ValidationError("Room password is required before match creation.")
        room_notes = room_notes.strip() if room_notes else None

        snapshot.queue.room_code = room_code
        snapshot.queue.room_password = room_password
        snapshot.queue.room_notes = room_notes
        snapshot.queue.room_info_submitted_by_player_id = submitter_player_id
        match_snapshot = await repository.create_match_from_queue(
            snapshot,
            result_deadline_at=seconds_from_now(self.settings.result_timeout_seconds),
        )
        snapshot.queue.state = QueueState.CONVERTED_TO_MATCH
        snapshot.queue.converted_match_id = match_snapshot.match.id
        snapshot.queue.converted_at = utcnow()
        for player in match_snapshot.players:
            await self.profile_service.set_match_activity(profile_repository, player.player_id, match_snapshot.match.id)
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.queue.guild_id,
            action=AuditAction.ROOM_INFO_SUBMITTED,
            entity_type=AuditEntityType.MATCH,
            entity_id=str(match_snapshot.match.id),
            actor_player_id=submitter_player_id,
            metadata_json={"queue_id": str(queue_id)},
        )
        return match_snapshot

    async def mark_match_live(
        self,
        repository: MatchRepository,
        *,
        match_id: UUID,
        result_channel_id: int | None,
        result_message_id: int | None,
        team1_voice_channel_id: int | None,
        team2_voice_channel_id: int | None,
    ) -> MatchSnapshot:
        snapshot = await repository.get_match_snapshot(match_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Match not found.")
        if snapshot.match.state not in {MatchState.CREATED, MatchState.MOVING}:
            return snapshot
        snapshot.match.state = MatchState.LIVE
        snapshot.match.result_channel_id = result_channel_id
        snapshot.match.result_message_id = result_message_id
        snapshot.match.team1_voice_channel_id = team1_voice_channel_id
        snapshot.match.team2_voice_channel_id = team2_voice_channel_id
        snapshot.match.live_at = utcnow()
        return snapshot

    async def submit_vote(
        self,
        repository: MatchRepository,
        *,
        match_id: UUID,
        player_id: int,
        winner_team_number: int,
        winner_mvp_player_id: int | None,
        loser_mvp_player_id: int | None,
    ) -> MatchSnapshot:
        validate_team_number(winner_team_number)
        snapshot = await repository.get_match_snapshot(match_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Match not found.")
        if snapshot.match.state not in {MatchState.LIVE, MatchState.RESULT_PENDING}:
            raise StateTransitionError("Voting is not open for that match.")
        if player_id not in snapshot.participant_ids:
            raise ValidationError("Only match participants can vote.")
        self.validate_result_payload(
            snapshot,
            winner_team_number=winner_team_number,
            winner_mvp_player_id=winner_mvp_player_id,
            loser_mvp_player_id=loser_mvp_player_id,
        )
        snapshot.match.state = MatchState.RESULT_PENDING
        await repository.supersede_active_vote(match_id, player_id)
        await repository.create_vote(
            match_id=match_id,
            player_id=player_id,
            winner_team_number=winner_team_number,
            winner_mvp_player_id=winner_mvp_player_id,
            loser_mvp_player_id=loser_mvp_player_id,
        )
        refreshed = await repository.get_match_snapshot(match_id, for_update=True)
        assert refreshed is not None
        return refreshed

    async def confirm_match(
        self,
        repository: MatchRepository,
        profile_repository: ProfileRepository,
        season_repository: SeasonRepository,
        rank_repository: RankRepository,
        economy_repository: EconomyRepository,
        moderation_repository: ModerationRepository,
        *,
        match_id: UUID,
        winner_team_number: int,
        winner_mvp_player_id: int | None,
        loser_mvp_player_id: int | None,
        actor_player_id: int | None = None,
        source: str = "consensus",
    ) -> MatchSnapshot:
        snapshot = await repository.get_match_snapshot(match_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Match not found.")
        if snapshot.match.state not in MATCH_RESULT_OPEN_STATES:
            raise StateTransitionError("That match is not open for confirmation.")
        self.validate_result_payload(
            snapshot,
            winner_team_number=winner_team_number,
            winner_mvp_player_id=winner_mvp_player_id,
            loser_mvp_player_id=loser_mvp_player_id,
        )
        winner_ids = set(snapshot.team1_ids if winner_team_number == 1 else snapshot.team2_ids)
        season_players = await season_repository.get_season_players(snapshot.match.season_id, snapshot.participant_ids)
        if len(season_players) != len(snapshot.participant_ids):
            missing_count = len(snapshot.participant_ids) - len(season_players)
            raise ValidationError(f"Season progression data is missing for {missing_count} match participant(s).")
        tiers = await self.rank_service.ensure_default_tiers(rank_repository, snapshot.match.guild_id)
        ranking = await self.rank_service.apply_match_result(
            rank_repository,
            season_players=season_players,
            tiers=tiers,
            match_id=snapshot.match.id,
            winner_player_ids=winner_ids,
            actor_player_id=actor_player_id,
        )
        coin_deltas = await self.economy_service.grant_ranked_match_rewards(
            economy_repository,
            match_id=snapshot.match.id,
            participant_ids=snapshot.participant_ids,
            winner_ids=winner_ids,
            winner_mvp_id=winner_mvp_player_id,
            loser_mvp_id=loser_mvp_player_id,
        )
        for row in snapshot.players:
            change = ranking.changes[row.player_id]
            row.rating_before = change.before
            row.rating_after = change.after
            row.rating_delta = change.delta
            row.coins_delta = coin_deltas[row.player_id]
            row.result = MatchPlayerResult.WIN if row.player_id in winner_ids else MatchPlayerResult.LOSS
            row.is_winner_mvp = row.player_id == winner_mvp_player_id
            row.is_loser_mvp = row.player_id == loser_mvp_player_id
        snapshot.match.state = MatchState.CONFIRMED
        snapshot.match.result_source = source
        snapshot.match.confirmed_at = utcnow()
        await self.profile_service.clear_activity(profile_repository, snapshot.participant_ids)
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.match.guild_id,
            action=AuditAction.MATCH_CONFIRMED,
            entity_type=AuditEntityType.MATCH,
            entity_id=str(snapshot.match.id),
            actor_player_id=actor_player_id,
            metadata_json={"winner_team_number": winner_team_number, "source": source},
        )
        return snapshot

    async def expire_match(
        self,
        repository: MatchRepository,
        moderation_repository: ModerationRepository,
        *,
        match_id: UUID,
    ) -> MatchSnapshot:
        snapshot = await repository.get_match_snapshot(match_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Match not found.")
        if snapshot.match.state not in {MatchState.LIVE, MatchState.RESULT_PENDING}:
            return snapshot
        snapshot.match.state = MatchState.EXPIRED
        snapshot.match.closed_at = utcnow()
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.match.guild_id,
            action=AuditAction.MATCH_EXPIRED,
            entity_type=AuditEntityType.MATCH,
            entity_id=str(snapshot.match.id),
        )
        return snapshot

    async def force_close_match(
        self,
        repository: MatchRepository,
        profile_repository: ProfileRepository,
        moderation_repository: ModerationRepository,
        *,
        match_id: UUID,
        actor_player_id: int,
        reason: str,
    ) -> MatchSnapshot:
        snapshot = await repository.get_match_snapshot(match_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Match not found.")
        if snapshot.match.state == MatchState.CONFIRMED:
            raise StateTransitionError("That match is already confirmed.")
        snapshot.match.state = MatchState.FORCE_CLOSED
        snapshot.match.force_close_reason = reason
        snapshot.match.closed_at = utcnow()
        await self.profile_service.clear_activity(profile_repository, snapshot.participant_ids)
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.match.guild_id,
            action=AuditAction.MATCH_FORCE_CLOSED,
            entity_type=AuditEntityType.MATCH,
            entity_id=str(snapshot.match.id),
            actor_player_id=actor_player_id,
            reason=reason,
        )
        return snapshot
