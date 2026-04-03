from __future__ import annotations

from dataclasses import dataclass

from highlight_manager.db.models.competitive import MatchModel, MatchPlayerModel, MatchVoteModel, QueueModel, QueuePlayerModel


@dataclass(slots=True)
class QueueSnapshot:
    queue: QueueModel
    players: list[QueuePlayerModel]
    player_discord_ids: dict[int, int]

    @property
    def team1_ids(self) -> list[int]:
        return [row.player_id for row in self.players if row.team_number == 1]

    @property
    def team2_ids(self) -> list[int]:
        return [row.player_id for row in self.players if row.team_number == 2]

    @property
    def is_full(self) -> bool:
        return len(self.team1_ids) == self.queue.team_size and len(self.team2_ids) == self.queue.team_size


@dataclass(slots=True)
class MatchSnapshot:
    match: MatchModel
    players: list[MatchPlayerModel]
    votes: list[MatchVoteModel]
    player_discord_ids: dict[int, int]

    @property
    def team1_ids(self) -> list[int]:
        return [row.player_id for row in self.players if row.team_number == 1]

    @property
    def team2_ids(self) -> list[int]:
        return [row.player_id for row in self.players if row.team_number == 2]

    @property
    def participant_ids(self) -> list[int]:
        return [row.player_id for row in self.players]

    def all_votes_match(self) -> bool:
        if len(self.votes) != len(self.players) or not self.votes:
            return False
        first = self.votes[0]
        for vote in self.votes[1:]:
            if (
                vote.winner_team_number != first.winner_team_number
                or vote.winner_mvp_player_id != first.winner_mvp_player_id
                or vote.loser_mvp_player_id != first.loser_mvp_player_id
            ):
                return False
        return True
