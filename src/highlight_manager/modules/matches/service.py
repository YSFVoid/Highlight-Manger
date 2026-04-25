from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from uuid import UUID

from highlight_manager.app.config import Settings
from highlight_manager.modules.common.enums import (
    AuditAction,
    AuditEntityType,
    MatchPlayerResult,
    MatchResultPhase,
    MatchState,
    QueueState,
)
from highlight_manager.modules.common.exceptions import NotFoundError, StateTransitionError, ValidationError
from highlight_manager.modules.common.time import seconds_from_now, utcnow
from highlight_manager.modules.economy.repository import EconomyRepository
from highlight_manager.modules.economy.service import EconomyService
from highlight_manager.modules.matches.repository import MatchRepository
from highlight_manager.modules.matches.states import MATCH_RESULT_OPEN_STATES, QUEUE_JOINABLE_STATES, QUEUE_MUTABLE_STATES
from highlight_manager.modules.matches.types import (
    MatchReviewInboxItem,
    RematchAbuseDecision,
    MatchRoomUpdateHistoryItem,
    MatchSnapshot,
    QueueSnapshot,
)
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
    CAPTAIN_WINDOW_SECONDS = 180
    READY_CHECK_TIMEOUT_SECONDS = 60
    ANTI_REMATCH_LOOKBACK_HOURS = 24
    ANTI_REMATCH_REQUIRED_PRIOR_MATCHES = 2
    ANTI_REMATCH_OVERLAP_RATIO = 0.75

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

    @staticmethod
    def _datetime_sort_value(value: datetime | None) -> float:
        if value is None:
            return float("inf")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.timestamp()

    @staticmethod
    def _deadline_due(deadline: datetime | None, now: datetime) -> bool:
        if deadline is None:
            return False
        if deadline.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif deadline.tzinfo is not None and now.tzinfo is None:
            deadline = deadline.replace(tzinfo=None)
        return deadline <= now

    @classmethod
    def _review_deadlines_due(cls, snapshot: MatchSnapshot, now: datetime) -> list[datetime]:
        deadlines = [
            snapshot.match.result_deadline_at,
            snapshot.match.captain_deadline_at,
            snapshot.match.fallback_deadline_at,
        ]
        return [deadline for deadline in deadlines if cls._deadline_due(deadline, now)]

    @classmethod
    def _anti_rematch_overlap_threshold(cls, team_size: int) -> int:
        return max(1, ceil(team_size * cls.ANTI_REMATCH_OVERLAP_RATIO))

    @staticmethod
    def _team_sets(snapshot: MatchSnapshot) -> tuple[set[int], set[int]]:
        return set(snapshot.team1_ids), set(snapshot.team2_ids)

    @classmethod
    def _best_team_alignment(
        cls,
        current: MatchSnapshot,
        candidate: MatchSnapshot,
    ) -> tuple[int, int]:
        current_team1, current_team2 = cls._team_sets(current)
        candidate_team1, candidate_team2 = cls._team_sets(candidate)
        direct = (
            len(current_team1 & candidate_team1),
            len(current_team2 & candidate_team2),
        )
        swapped = (
            len(current_team1 & candidate_team2),
            len(current_team2 & candidate_team1),
        )
        if sum(swapped) > sum(direct):
            return swapped
        if sum(swapped) == sum(direct) and min(swapped) > min(direct):
            return swapped
        return direct

    @classmethod
    def _classify_rematch_candidate(
        cls,
        current: MatchSnapshot,
        candidate: MatchSnapshot,
    ) -> tuple[str, int, int] | None:
        overlap_team1, overlap_team2 = cls._best_team_alignment(current, candidate)
        team_size = current.match.team_size
        if overlap_team1 == team_size and overlap_team2 == team_size:
            return "exact_repeat", overlap_team1, overlap_team2
        overlap_threshold = cls._anti_rematch_overlap_threshold(team_size)
        if overlap_team1 >= overlap_threshold and overlap_team2 >= overlap_threshold:
            return "high_overlap_repeat", overlap_team1, overlap_team2
        return None

    @classmethod
    def _build_anti_rematch_staff_detail(cls, decision: RematchAbuseDecision) -> str:
        prior_matches = ", ".join(f"#{number:03d}" for number in decision.prior_match_numbers)
        return (
            f"Prior similar matches: {prior_matches}\n"
            f"Overlap: {decision.best_overlap_team1}/{decision.overlap_threshold} vs "
            f"{decision.best_overlap_team2}/{decision.overlap_threshold}"
        )

    async def _detect_anti_rematch_abuse(
        self,
        repository: MatchRepository,
        snapshot: MatchSnapshot,
        *,
        source: str,
        now: datetime,
    ) -> RematchAbuseDecision | None:
        confirmed_after = now - timedelta(hours=self.ANTI_REMATCH_LOOKBACK_HOURS)
        candidates = await repository.list_recent_confirmed_rematch_candidates(
            guild_id=snapshot.match.guild_id,
            season_id=snapshot.match.season_id,
            ruleset_key=snapshot.match.ruleset_key,
            mode=snapshot.match.mode,
            match_id=snapshot.match.id,
            confirmed_after=confirmed_after,
            now=now,
        )

        matches: list[tuple[MatchSnapshot, str, int, int]] = []
        for candidate in candidates:
            candidate_snapshot = await repository.get_match_snapshot(candidate.id)
            if candidate_snapshot is None:
                continue
            classification = self._classify_rematch_candidate(snapshot, candidate_snapshot)
            if classification is None:
                continue
            reason, overlap_team1, overlap_team2 = classification
            matches.append((candidate_snapshot, reason, overlap_team1, overlap_team2))

        if len(matches) < self.ANTI_REMATCH_REQUIRED_PRIOR_MATCHES:
            return None

        matches.sort(
            key=lambda item: (
                item[0].match.confirmed_at or item[0].match.created_at,
                item[0].match.match_number,
            )
        )
        primary_reason = "exact_repeat" if any(reason == "exact_repeat" for _, reason, _, _ in matches) else "high_overlap_repeat"
        prior_match_ids = [str(candidate.match.id) for candidate, _, _, _ in matches]
        prior_match_numbers = [candidate.match.match_number for candidate, _, _, _ in matches]
        best_overlap_team1 = max(overlap_team1 for _, _, overlap_team1, _ in matches)
        best_overlap_team2 = max(overlap_team2 for _, _, _, overlap_team2 in matches)
        return RematchAbuseDecision(
            reason=primary_reason,
            prior_match_ids=prior_match_ids,
            prior_match_numbers=prior_match_numbers,
            matched_prior_count=len(matches),
            overlap_threshold=self._anti_rematch_overlap_threshold(snapshot.match.team_size),
            best_overlap_team1=best_overlap_team1,
            best_overlap_team2=best_overlap_team2,
            trigger_source=source,
        )

    @classmethod
    def _classify_review_inbox_item(
        cls,
        snapshot: MatchSnapshot,
        now: datetime,
    ) -> MatchReviewInboxItem | None:
        match = snapshot.match
        if match.state == MatchState.EXPIRED or snapshot.result_phase == MatchResultPhase.STAFF_REVIEW:
            sort_at = match.closed_at or match.result_deadline_at or match.created_at
            return MatchReviewInboxItem(
                snapshot=snapshot,
                reason="staff_review",
                reason_label="Staff review",
                severity=0,
                sort_at=sort_at,
                staff_detail=None,
            )

        due_deadlines = cls._review_deadlines_due(snapshot, now)
        if match.state in {MatchState.LIVE, MatchState.RESULT_PENDING} and due_deadlines:
            return MatchReviewInboxItem(
                snapshot=snapshot,
                reason="overdue",
                reason_label="Overdue",
                severity=1,
                sort_at=min(due_deadlines, key=cls._datetime_sort_value),
                staff_detail=None,
            )

        if snapshot.phase_votes_disagree:
            first_vote_at = snapshot.phase_votes[0].created_at if snapshot.phase_votes else None
            return MatchReviewInboxItem(
                snapshot=snapshot,
                reason="disputed",
                reason_label="Disputed votes",
                severity=2,
                sort_at=first_vote_at or match.created_at,
                staff_detail=None,
            )
        return None

    async def list_review_inbox(
        self,
        repository: MatchRepository,
        moderation_repository: ModerationRepository,
        *,
        guild_id: int,
        now: datetime | None = None,
        limit: int | None = 10,
    ) -> list[MatchReviewInboxItem]:
        now = now or utcnow()
        requested_limit = 10 if limit is None else limit
        display_limit = min(max(requested_limit, 1), 25)
        candidate_limit = max(display_limit * 4, 25)
        candidates = await repository.list_review_inbox_candidates(
            guild_id,
            now=now,
            limit=candidate_limit,
        )

        items: list[MatchReviewInboxItem] = []
        for candidate in candidates:
            snapshot = await repository.get_match_snapshot(candidate.id)
            if snapshot is None:
                continue
            item = self._classify_review_inbox_item(snapshot, now)
            if item is not None:
                if item.reason == "staff_review":
                    anti_rematch_audit = await moderation_repository.get_match_anti_rematch_audit(snapshot.match.id)
                    if anti_rematch_audit is not None:
                        metadata = anti_rematch_audit.metadata_json if isinstance(anti_rematch_audit.metadata_json, dict) else {}
                        prior_numbers = metadata.get("prior_match_numbers", [])
                        if isinstance(prior_numbers, list):
                            prior_match_numbers = [
                                int(value)
                                for value in prior_numbers
                                if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
                            ]
                        else:
                            prior_match_numbers = []
                        decision = RematchAbuseDecision(
                            reason=str(metadata.get("reason", "high_overlap_repeat")),
                            prior_match_ids=[
                                str(value)
                                for value in metadata.get("prior_match_ids", [])
                                if value is not None
                            ],
                            prior_match_numbers=prior_match_numbers,
                            matched_prior_count=int(metadata.get("matched_prior_count", len(prior_match_numbers) or 0)),
                            overlap_threshold=int(metadata.get("overlap_threshold", self._anti_rematch_overlap_threshold(snapshot.match.team_size))),
                            best_overlap_team1=int(metadata.get("best_overlap_team1", 0)),
                            best_overlap_team2=int(metadata.get("best_overlap_team2", 0)),
                            trigger_source=str(metadata.get("trigger_source", "consensus")),
                        )
                        item.reason_label = "Suspicious rematch"
                        item.staff_detail = self._build_anti_rematch_staff_detail(decision)
                items.append(item)

        items.sort(
            key=lambda item: (
                item.severity,
                self._datetime_sort_value(item.sort_at),
                item.snapshot.match.match_number,
            )
        )
        return items[:display_limit]

    async def count_review_inbox_by_reason(
        self,
        repository: MatchRepository,
        *,
        guild_id: int,
        now: datetime | None = None,
    ) -> dict[str, int]:
        now = now or utcnow()
        counts = {"staff_review": 0, "overdue": 0, "disputed": 0}
        candidates = await repository.list_review_inbox_candidates(
            guild_id,
            now=now,
            limit=None,
        )
        for candidate in candidates:
            snapshot = await repository.get_match_snapshot(candidate.id)
            if snapshot is None:
                continue
            item = self._classify_review_inbox_item(snapshot, now)
            if item is not None:
                counts[item.reason] = counts.get(item.reason, 0) + 1
        counts["total"] = sum(counts.values())
        return counts

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
        existing = await self.get_active_queue_for_playlist(
            repository,
            guild_id=guild_id,
            ruleset_key=ruleset_key,
            mode=mode,
        )
        if existing is not None:
            return existing
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

    async def get_active_queue_for_playlist(
        self,
        repository: MatchRepository,
        *,
        guild_id: int,
        ruleset_key,
        mode,
    ) -> QueueSnapshot | None:
        queue = await repository.get_active_queue_for_playlist(guild_id, ruleset_key, mode)
        if queue is None:
            return None
        snapshot = await repository.get_queue_snapshot(queue.id)
        if snapshot is not None:
            snapshot.reused_existing = True
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

        joined_row = await repository.add_queue_player(queue_id, player_id, team_number)
        await self.profile_service.set_queue_activity(profile_repository, player_id, queue_id)
        snapshot.players.append(joined_row)
        snapshot.player_discord_ids.update(await repository.get_player_discord_ids([player_id]))
        if snapshot.is_full:
            snapshot.queue.state = QueueState.READY_CHECK
            snapshot.queue.full_at = utcnow()
            snapshot.queue.room_info_deadline_at = seconds_from_now(self.READY_CHECK_TIMEOUT_SECONDS)
            snapshot.queue.room_info_reminder_sent_at = None
        else:
            snapshot.queue.state = QueueState.FILLING
            snapshot.queue.room_info_deadline_at = None
            snapshot.queue.room_info_reminder_sent_at = None
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

    async def mark_ready(
        self,
        repository: MatchRepository,
        profile_repository: ProfileRepository,
        *,
        queue_id: UUID,
        player_id: int,
    ) -> QueueSnapshot:
        snapshot = await repository.get_queue_snapshot(queue_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Queue not found.")
        if snapshot.queue.state != QueueState.READY_CHECK:
            raise StateTransitionError("Queue is not in ready check phase.")
        if not any(row.player_id == player_id for row in snapshot.players):
            raise ValidationError("You are not in this queue.")
        if player_id in snapshot.ready_player_ids:
            raise ValidationError("You are already marked as ready.")

        ready_row = await repository.mark_queue_player_ready(queue_id, player_id)
        if ready_row is None:
            raise ValidationError("You are not in this queue.")
        for row in snapshot.players:
            if row.player_id == player_id:
                row.ready_at = ready_row.ready_at
                break
        snapshot.ready_player_ids.add(player_id)
        if snapshot.all_ready:
            snapshot.queue.state = QueueState.FULL_PENDING_ROOM_INFO
            snapshot.queue.room_info_deadline_at = seconds_from_now(self.settings.room_info_timeout_seconds)
            snapshot.queue.room_info_reminder_sent_at = None
        return snapshot

    async def transfer_queue_host(
        self,
        repository: MatchRepository,
        moderation_repository: ModerationRepository,
        *,
        queue_id: UUID,
        actor_player_id: int,
        target_player_id: int,
        actor_is_staff: bool,
    ) -> QueueSnapshot:
        snapshot = await repository.get_queue_snapshot(queue_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Queue not found.")
        if snapshot.queue.state not in QUEUE_MUTABLE_STATES:
            raise StateTransitionError("That queue is already closed.")
        old_creator_player_id = snapshot.queue.creator_player_id
        if actor_player_id != old_creator_player_id and not actor_is_staff:
            raise ValidationError("Only the current host or staff can transfer queue host.")
        if target_player_id == old_creator_player_id:
            raise ValidationError("That player is already the queue host.")
        if not any(row.player_id == target_player_id for row in snapshot.players):
            raise ValidationError("New host must already be in this queue.")

        queue = await repository.set_queue_creator(queue_id, target_player_id)
        if queue is None:
            raise NotFoundError("Queue not found.")
        snapshot.queue = queue
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.queue.guild_id,
            action=AuditAction.QUEUE_HOST_TRANSFERRED,
            entity_type=AuditEntityType.QUEUE,
            entity_id=str(queue_id),
            actor_player_id=actor_player_id,
            target_player_id=target_player_id,
            metadata_json={
                "old_creator_player_id": old_creator_player_id,
                "new_creator_player_id": target_player_id,
                "queue_state": snapshot.queue.state.value,
            },
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
        reason: str | None = None,
    ) -> QueueSnapshot:
        snapshot = await repository.get_queue_snapshot(queue_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Queue not found.")
        row = next((item for item in snapshot.players if item.player_id == player_id), None)
        if row is None:
            raise ValidationError("You are not in that queue.")
        was_ready_check = snapshot.queue.state == QueueState.READY_CHECK
        await repository.delete_queue_player(row)
        await self.profile_service.clear_activity(profile_repository, [player_id])
        snapshot.players = [item for item in snapshot.players if item.player_id != player_id]
        snapshot.ready_player_ids.discard(player_id)
        if player_id == snapshot.queue.creator_player_id or snapshot.queue.state == QueueState.FULL_PENDING_ROOM_INFO:
            cancel_reason = reason or (
                "host_left"
                if player_id == snapshot.queue.creator_player_id
                else "locked_queue_player_left"
            )
            snapshot.queue.state = QueueState.QUEUE_CANCELLED
            snapshot.queue.cancel_reason = cancel_reason
            snapshot.queue.cancelled_at = utcnow()
            await self.profile_service.clear_activity(profile_repository, [row.player_id for row in snapshot.players])
            await self.moderation_service.audit(
                moderation_repository,
                guild_id=snapshot.queue.guild_id,
                action=AuditAction.QUEUE_CANCELLED,
                entity_type=AuditEntityType.QUEUE,
                entity_id=str(queue_id),
                actor_player_id=player_id,
                reason=cancel_reason,
            )
            return snapshot
        snapshot.queue.state = QueueState.FILLING if snapshot.players else QueueState.QUEUE_CANCELLED
        if was_ready_check and snapshot.queue.state == QueueState.FILLING:
            await repository.clear_queue_ready_state(queue_id)
            snapshot.ready_player_ids.clear()
            for item in snapshot.players:
                item.ready_at = None
            snapshot.queue.room_info_deadline_at = None
            snapshot.queue.room_info_reminder_sent_at = None
        if not snapshot.players:
            snapshot.queue.cancel_reason = reason or "empty_queue"
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
        await self.profile_service.set_match_activity_for_players(
            profile_repository,
            [player.player_id for player in match_snapshot.players],
            match_snapshot.match.id,
        )
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
        snapshot.match.result_phase = MatchResultPhase.CAPTAIN
        snapshot.match.result_channel_id = result_channel_id
        snapshot.match.result_message_id = result_message_id
        snapshot.match.team1_voice_channel_id = team1_voice_channel_id
        snapshot.match.team2_voice_channel_id = team2_voice_channel_id
        snapshot.match.captain_deadline_at = seconds_from_now(self.CAPTAIN_WINDOW_SECONDS)
        snapshot.match.fallback_deadline_at = seconds_from_now(self.settings.result_timeout_seconds)
        snapshot.match.result_deadline_at = snapshot.match.fallback_deadline_at
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
        if snapshot.match.result_phase == MatchResultPhase.STAFF_REVIEW:
            raise StateTransitionError("Player voting is closed. Staff review is now required.")
        if snapshot.match.result_phase == MatchResultPhase.CAPTAIN:
            if player_id not in snapshot.captain_ids:
                raise ValidationError("Only the two team captains can vote during the captain window.")
        elif player_id not in snapshot.participant_ids:
            raise ValidationError("Only match participants can vote.")
        self.validate_result_payload(
            snapshot,
            winner_team_number=winner_team_number,
            winner_mvp_player_id=winner_mvp_player_id,
            loser_mvp_player_id=loser_mvp_player_id,
        )
        snapshot.match.state = MatchState.RESULT_PENDING
        await repository.supersede_active_vote(match_id, player_id)
        new_vote = await repository.create_vote(
            match_id=match_id,
            player_id=player_id,
            winner_team_number=winner_team_number,
            winner_mvp_player_id=winner_mvp_player_id,
            loser_mvp_player_id=loser_mvp_player_id,
        )
        snapshot.votes = [vote for vote in snapshot.votes if vote.player_id != player_id]
        snapshot.votes.append(new_vote)
        return snapshot

    async def open_fallback_voting(
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
        if snapshot.match.result_phase != MatchResultPhase.CAPTAIN:
            return snapshot
        snapshot.match.state = MatchState.RESULT_PENDING
        snapshot.match.result_phase = MatchResultPhase.FALLBACK
        if snapshot.match.fallback_deadline_at is None:
            snapshot.match.fallback_deadline_at = seconds_from_now(self.settings.result_timeout_seconds)
        snapshot.match.result_deadline_at = snapshot.match.fallback_deadline_at
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.match.guild_id,
            action=AuditAction.MATCH_RESULT_FALLBACK_OPENED,
            entity_type=AuditEntityType.MATCH,
            entity_id=str(snapshot.match.id),
            metadata_json={"captain_votes": len(snapshot.phase_votes)},
        )
        return snapshot

    async def update_room_info(
        self,
        repository: MatchRepository,
        moderation_repository: ModerationRepository,
        *,
        match_id: UUID,
        creator_player_id: int,
        room_code: str,
        room_password: str | None,
        room_notes: str | None,
    ) -> MatchSnapshot:
        snapshot = await repository.get_match_snapshot(match_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Match not found.")
        if snapshot.match.creator_player_id != creator_player_id:
            raise ValidationError("Only the match creator can update room info.")
        if snapshot.match.state not in {MatchState.LIVE, MatchState.RESULT_PENDING}:
            raise StateTransitionError("Room info cannot be updated for that match right now.")
        if snapshot.votes:
            raise ValidationError("Room info is locked after the first vote.")
        if snapshot.match.rehost_count >= 1:
            raise ValidationError("Room info can only be updated once after the match goes live.")
        before_room_code = snapshot.match.room_code
        before_room_password = snapshot.match.room_password
        before_room_notes = snapshot.match.room_notes
        rehost_count_before = snapshot.match.rehost_count
        room_code = room_code.strip()
        if not room_code:
            raise ValidationError("Room ID is required.")
        room_password = (room_password or "").strip()
        if not room_password:
            raise ValidationError("Room password is required.")
        room_notes = room_notes.strip() if room_notes else None
        await repository.update_match_room_info(
            snapshot.match,
            room_code=room_code,
            room_password=room_password,
            room_notes=room_notes,
        )
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.match.guild_id,
            action=AuditAction.MATCH_REHOSTED,
            entity_type=AuditEntityType.MATCH,
            entity_id=str(snapshot.match.id),
            actor_player_id=creator_player_id,
            metadata_json={
                "before_room_code": before_room_code,
                "before_room_password": before_room_password,
                "before_room_notes": before_room_notes,
                "after_room_code": snapshot.match.room_code,
                "after_room_password": snapshot.match.room_password,
                "after_room_notes": snapshot.match.room_notes,
                "rehost_count_before": rehost_count_before,
                "rehost_count_after": snapshot.match.rehost_count,
            },
        )
        return snapshot

    async def list_room_update_history(
        self,
        repository: MatchRepository,
        moderation_repository: ModerationRepository,
        *,
        match_id: UUID,
        limit: int | None = 10,
    ) -> list[MatchRoomUpdateHistoryItem]:
        requested_limit = 10 if limit is None else limit
        display_limit = min(max(requested_limit, 1), 10)
        audit_rows = await moderation_repository.list_match_rehost_audits(match_id, limit=display_limit)
        actor_player_ids = [
            audit.actor_player_id
            for audit in audit_rows
            if audit.actor_player_id is not None
        ]
        actor_lookup = await repository.get_player_discord_ids(actor_player_ids)

        items: list[MatchRoomUpdateHistoryItem] = []
        for audit in reversed(audit_rows):
            metadata = audit.metadata_json if isinstance(audit.metadata_json, dict) else {}
            has_detailed_metadata = any(
                key in metadata
                for key in (
                    "before_room_code",
                    "before_room_password",
                    "before_room_notes",
                    "after_room_code",
                    "after_room_password",
                    "after_room_notes",
                    "rehost_count_before",
                    "rehost_count_after",
                )
            )
            items.append(
                MatchRoomUpdateHistoryItem(
                    actor_player_id=audit.actor_player_id,
                    actor_discord_id=actor_lookup.get(audit.actor_player_id) if audit.actor_player_id is not None else None,
                    created_at=audit.created_at,
                    before_room_code=metadata.get("before_room_code"),
                    before_room_password=metadata.get("before_room_password"),
                    before_room_notes=metadata.get("before_room_notes"),
                    after_room_code=metadata.get("after_room_code"),
                    after_room_password=metadata.get("after_room_password"),
                    after_room_notes=metadata.get("after_room_notes"),
                    rehost_count_before=metadata.get("rehost_count_before"),
                    rehost_count_after=metadata.get("rehost_count_after"),
                    legacy=not has_detailed_metadata,
                )
            )
        return items

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
        now = utcnow()
        if source != "force_result":
            anti_rematch_decision = await self._detect_anti_rematch_abuse(
                repository,
                snapshot,
                source=source,
                now=now,
            )
            if anti_rematch_decision is not None:
                snapshot.match.state = MatchState.RESULT_PENDING
                snapshot.match.result_phase = MatchResultPhase.STAFF_REVIEW
                snapshot.anti_rematch_decision = anti_rematch_decision
                await self.moderation_service.audit(
                    moderation_repository,
                    guild_id=snapshot.match.guild_id,
                    action=AuditAction.MATCH_ANTI_REMATCH_FLAGGED,
                    entity_type=AuditEntityType.MATCH,
                    entity_id=str(snapshot.match.id),
                    actor_player_id=actor_player_id,
                    metadata_json={
                        "reason": anti_rematch_decision.reason,
                        "lookback_hours": self.ANTI_REMATCH_LOOKBACK_HOURS,
                        "required_prior_matches": self.ANTI_REMATCH_REQUIRED_PRIOR_MATCHES,
                        "prior_match_ids": anti_rematch_decision.prior_match_ids,
                        "prior_match_numbers": anti_rematch_decision.prior_match_numbers,
                        "matched_prior_count": anti_rematch_decision.matched_prior_count,
                        "overlap_threshold": anti_rematch_decision.overlap_threshold,
                        "best_overlap_team1": anti_rematch_decision.best_overlap_team1,
                        "best_overlap_team2": anti_rematch_decision.best_overlap_team2,
                        "trigger_source": anti_rematch_decision.trigger_source,
                    },
                )
                return snapshot
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
            ruleset_key=snapshot.match.ruleset_key,
            winner_mvp_player_id=winner_mvp_player_id,
            loser_mvp_player_id=loser_mvp_player_id,
            actor_player_id=actor_player_id,
        )
        coin_rewards = await self.economy_service.grant_ranked_match_rewards(
            economy_repository,
            match_id=snapshot.match.id,
            participant_ids=snapshot.participant_ids,
            winner_ids=winner_ids,
            winner_mvp_id=winner_mvp_player_id,
            loser_mvp_id=loser_mvp_player_id,
        )
        snapshot.coins_summary = coin_rewards
        for row in snapshot.players:
            change = ranking.changes[row.player_id]
            row.rating_before = change.before
            row.rating_after = change.after
            row.rating_delta = change.delta
            player_rewards = coin_rewards.get(row.player_id, {})
            row.coins_delta = sum(player_rewards.values())
            row.result = MatchPlayerResult.WIN if row.player_id in winner_ids else MatchPlayerResult.LOSS
            row.is_winner_mvp = row.player_id == winner_mvp_player_id
            row.is_loser_mvp = row.player_id == loser_mvp_player_id
        snapshot.match.state = MatchState.CONFIRMED
        snapshot.match.result_source = source
        snapshot.match.confirmed_at = now
        snapshot.match.closed_at = now
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

    async def cancel_match_by_creator(
        self,
        repository: MatchRepository,
        profile_repository: ProfileRepository,
        moderation_repository: ModerationRepository,
        *,
        match_id: UUID,
        creator_player_id: int,
        reason: str = "creator_cancelled",
    ) -> MatchSnapshot:
        snapshot = await repository.get_match_snapshot(match_id, for_update=True)
        if snapshot is None:
            raise NotFoundError("Match not found.")
        if snapshot.match.creator_player_id != creator_player_id:
            raise ValidationError("Only the match creator can cancel this match.")
        if snapshot.match.state not in {MatchState.LIVE, MatchState.RESULT_PENDING}:
            raise StateTransitionError("That match cannot be cancelled by the creator right now.")
        if snapshot.votes:
            raise ValidationError("Creator cancel is locked after the first result vote.")
        snapshot.match.state = MatchState.CANCELLED
        snapshot.match.cancel_reason = reason
        snapshot.match.closed_at = utcnow()
        await self.profile_service.clear_activity(profile_repository, snapshot.participant_ids)
        await self.moderation_service.audit(
            moderation_repository,
            guild_id=snapshot.match.guild_id,
            action=AuditAction.MATCH_FORCE_CLOSED,
            entity_type=AuditEntityType.MATCH,
            entity_id=str(snapshot.match.id),
            actor_player_id=creator_player_id,
            reason=reason,
            metadata_json={"source": "creator_cancel"},
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
        snapshot.match.result_phase = MatchResultPhase.STAFF_REVIEW
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
