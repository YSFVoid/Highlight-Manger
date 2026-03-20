from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from highlight_manager.config.logging import get_logger
from highlight_manager.models.match import MatchRecord
from highlight_manager.models.vote import MatchVote
from highlight_manager.repositories.vote_repository import VoteRepository
from highlight_manager.utils.dates import utcnow
from highlight_manager.utils.exceptions import UserFacingError


@dataclass(slots=True)
class ConsensusResult:
    winner_team: int
    winner_mvp_id: int | None = None
    loser_mvp_id: int | None = None


class VoteService:
    def __init__(self, repository: VoteRepository) -> None:
        self.repository = repository
        self.logger = get_logger(__name__)

    async def submit_vote(
        self,
        match: MatchRecord,
        *,
        user_id: int,
        winner_team: int,
        winner_mvp_id: int | None,
        loser_mvp_id: int | None,
    ) -> MatchVote:
        self.validate_vote(
            match,
            user_id=user_id,
            winner_team=winner_team,
            winner_mvp_id=winner_mvp_id,
            loser_mvp_id=loser_mvp_id,
        )
        vote = MatchVote(
            guild_id=match.guild_id,
            match_number=match.match_number,
            user_id=user_id,
            winner_team=winner_team,
            winner_mvp_id=winner_mvp_id,
            loser_mvp_id=loser_mvp_id,
            updated_at=utcnow(),
        )
        saved = await self.repository.upsert(vote)
        self.logger.info("vote_submitted", guild_id=match.guild_id, match_number=match.match_number, user_id=user_id)
        return saved

    async def get_votes(self, match: MatchRecord) -> list[MatchVote]:
        return await self.repository.list_for_match(match.guild_id, match.match_number)

    async def clear_votes(self, match: MatchRecord) -> None:
        await self.repository.delete_for_match(match.guild_id, match.match_number)

    def validate_vote(
        self,
        match: MatchRecord,
        *,
        user_id: int,
        winner_team: int,
        winner_mvp_id: int | None,
        loser_mvp_id: int | None,
    ) -> None:
        if user_id not in match.all_player_ids:
            raise UserFacingError("Only match participants can vote.")
        self.validate_result_selection(
            match,
            winner_team=winner_team,
            winner_mvp_id=winner_mvp_id,
            loser_mvp_id=loser_mvp_id,
        )

    def validate_result_selection(
        self,
        match: MatchRecord,
        *,
        winner_team: int,
        winner_mvp_id: int | None,
        loser_mvp_id: int | None,
    ) -> None:
        if winner_team not in {1, 2}:
            raise UserFacingError("Winner team must be Team 1 or Team 2.")
        winner_ids = set(match.team1_player_ids if winner_team == 1 else match.team2_player_ids)
        loser_ids = set(match.team2_player_ids if winner_team == 1 else match.team1_player_ids)
        if match.mode.team_size == 1:
            if winner_mvp_id or loser_mvp_id:
                raise UserFacingError("1v1 matches do not use MVP voting.")
            return
        if winner_mvp_id not in winner_ids:
            raise UserFacingError("Winner MVP must belong to the winning team.")
        if loser_mvp_id not in loser_ids:
            raise UserFacingError("Loser MVP must belong to the losing team.")
        if winner_mvp_id == loser_mvp_id:
            raise UserFacingError("Winner MVP and Loser MVP cannot be the same player.")

    def compute_consensus(self, match: MatchRecord, votes: list[MatchVote]) -> ConsensusResult | None:
        total_players = len(match.all_player_ids)
        if len(votes) < total_players:
            return None

        winner_team_counts = Counter(vote.winner_team for vote in votes)
        winner_team, winner_team_count = winner_team_counts.most_common(1)[0]
        if winner_team_count <= total_players / 2:
            return None

        if match.mode.team_size == 1:
            return ConsensusResult(winner_team=winner_team)

        winner_ids = set(match.team1_player_ids if winner_team == 1 else match.team2_player_ids)
        loser_ids = set(match.team2_player_ids if winner_team == 1 else match.team1_player_ids)

        winner_mvp_counts = Counter(vote.winner_mvp_id for vote in votes if vote.winner_mvp_id in winner_ids)
        loser_mvp_counts = Counter(vote.loser_mvp_id for vote in votes if vote.loser_mvp_id in loser_ids)
        if not winner_mvp_counts or not loser_mvp_counts:
            return None

        winner_mvp_id, winner_mvp_count = winner_mvp_counts.most_common(1)[0]
        loser_mvp_id, loser_mvp_count = loser_mvp_counts.most_common(1)[0]
        if winner_mvp_count <= total_players / 2 or loser_mvp_count <= total_players / 2:
            return None

        return ConsensusResult(
            winner_team=winner_team,
            winner_mvp_id=winner_mvp_id,
            loser_mvp_id=loser_mvp_id,
        )
