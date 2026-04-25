from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass

from highlight_manager.db.models.competitive import MatchModel, MatchPlayerModel, MatchVoteModel, QueueModel, QueuePlayerModel
from highlight_manager.modules.common.enums import MatchResultPhase, MatchState


@dataclass(slots=True)
class QueueSnapshot:
    queue: QueueModel
    players: list[QueuePlayerModel]
    player_discord_ids: dict[int, int]
    ready_player_ids: set[int] | None = None
    reused_existing: bool = False

    def __post_init__(self) -> None:
        if self.ready_player_ids is None:
            self.ready_player_ids = {
                row.player_id for row in self.players if getattr(row, "ready_at", None) is not None
            }

    @property
    def team1_ids(self) -> list[int]:
        return [row.player_id for row in self.players if row.team_number == 1]

    @property
    def team2_ids(self) -> list[int]:
        return [row.player_id for row in self.players if row.team_number == 2]

    @property
    def is_full(self) -> bool:
        return len(self.team1_ids) == self.queue.team_size and len(self.team2_ids) == self.queue.team_size

    @property
    def all_ready(self) -> bool:
        all_ids = {row.player_id for row in self.players}
        return bool(all_ids) and all_ids == self.ready_player_ids


@dataclass(slots=True)
class MatchSnapshot:
    match: MatchModel
    players: list[MatchPlayerModel]
    votes: list[MatchVoteModel]
    player_discord_ids: dict[int, int]
    coins_summary: dict[int, dict[str, int]] = None
    anti_rematch_decision: RematchAbuseDecision | None = None

    def __post_init__(self):
        if self.coins_summary is None:
            self.coins_summary = {}

    @property
    def team1_ids(self) -> list[int]:
        return [row.player_id for row in self.players if row.team_number == 1]

    @property
    def team2_ids(self) -> list[int]:
        return [row.player_id for row in self.players if row.team_number == 2]

    @property
    def participant_ids(self) -> list[int]:
        return [row.player_id for row in self.players]

    @property
    def team1_captain_player_id(self) -> int | None:
        return self.match.team1_captain_player_id

    @property
    def team2_captain_player_id(self) -> int | None:
        return self.match.team2_captain_player_id

    @property
    def result_phase(self) -> MatchResultPhase:
        return self.match.result_phase or MatchResultPhase.CAPTAIN

    @property
    def captain_ids(self) -> list[int]:
        return [
            player_id
            for player_id in [self.match.team1_captain_player_id, self.match.team2_captain_player_id]
            if player_id is not None
        ]

    @property
    def active_voter_ids(self) -> list[int]:
        if self.result_phase == MatchResultPhase.CAPTAIN:
            return self.captain_ids
        if self.result_phase == MatchResultPhase.FALLBACK:
            return self.participant_ids
        return []

    @property
    def phase_votes(self) -> list[MatchVoteModel]:
        active_ids = set(self.active_voter_ids)
        return [vote for vote in self.votes if vote.player_id in active_ids]

    @property
    def creator_cancel_allowed(self) -> bool:
        return self.match.state in {MatchState.LIVE, MatchState.RESULT_PENDING} and self.result_phase != MatchResultPhase.STAFF_REVIEW and not self.votes

    @property
    def rehost_allowed(self) -> bool:
        return (
            self.match.state in {MatchState.LIVE, MatchState.RESULT_PENDING}
            and self.result_phase != MatchResultPhase.STAFF_REVIEW
            and self.match.rehost_count < 1
            and not self.votes
        )

    @property
    def captain_votes_match(self) -> bool:
        return self.votes_match(self.captain_ids)

    @property
    def fallback_votes_match(self) -> bool:
        return self.votes_match(self.participant_ids)

    def votes_match(self, voter_ids: list[int]) -> bool:
        if not voter_ids:
            return False
        phase_votes = [vote for vote in self.votes if vote.player_id in set(voter_ids)]
        if len(phase_votes) != len(voter_ids):
            return False
        first = phase_votes[0]
        for vote in phase_votes[1:]:
            if (
                vote.winner_team_number != first.winner_team_number
                or vote.winner_mvp_player_id != first.winner_mvp_player_id
                or vote.loser_mvp_player_id != first.loser_mvp_player_id
            ):
                return False
        return True

    def all_votes_match(self) -> bool:
        return self.votes_match(self.active_voter_ids)

    @property
    def phase_votes_disagree(self) -> bool:
        if len(self.phase_votes) < 2:
            return False
        first = self.phase_votes[0]
        for vote in self.phase_votes[1:]:
            if (
                vote.winner_team_number != first.winner_team_number
                or vote.winner_mvp_player_id != first.winner_mvp_player_id
                or vote.loser_mvp_player_id != first.loser_mvp_player_id
            ):
                return True
        return False


@dataclass(slots=True)
class MatchReviewInboxItem:
    snapshot: MatchSnapshot
    reason: str
    reason_label: str
    severity: int
    sort_at: datetime | None
    staff_detail: str | None = None


@dataclass(slots=True)
class RematchAbuseDecision:
    reason: str
    prior_match_ids: list[str]
    prior_match_numbers: list[int]
    matched_prior_count: int
    overlap_threshold: int
    best_overlap_team1: int
    best_overlap_team2: int
    trigger_source: str


@dataclass(slots=True)
class MatchRoomUpdateHistoryItem:
    actor_player_id: int | None
    actor_discord_id: int | None
    created_at: datetime
    before_room_code: str | None
    before_room_password: str | None
    before_room_notes: str | None
    after_room_code: str | None
    after_room_password: str | None
    after_room_notes: str | None
    rehost_count_before: int | None
    rehost_count_after: int | None
    legacy: bool = False
