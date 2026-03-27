from __future__ import annotations

from collections import defaultdict

from highlight_manager.models.tournament import TournamentMatchRecord, TournamentTeam


class TournamentStandingsService:
    def compute_group_standings(
        self,
        teams: list[TournamentTeam],
        matches: list[TournamentMatchRecord],
    ) -> dict[str, list[dict]]:
        teams_by_group: dict[str, list[TournamentTeam]] = defaultdict(list)
        for team in teams:
            if team.group_label:
                teams_by_group[team.group_label].append(team)

        direct_results: dict[tuple[int, int], int] = {}
        rows_by_group: dict[str, dict[int, dict]] = {}
        for group_label, group_teams in teams_by_group.items():
            rows_by_group[group_label] = {
                team.team_number: {
                    "team_id": team.team_number,
                    "points": 0,
                    "series_wins": 0,
                    "series_losses": 0,
                    "series_diff": 0,
                    "room_diff": 0,
                    "registered_at": team.registered_at,
                }
                for team in group_teams
            }

        for match in matches:
            if match.group_label is None or match.winner_team_id is None:
                continue
            rows = rows_by_group.get(match.group_label)
            if rows is None:
                continue
            loser_team_id = match.team2_id if match.winner_team_id == match.team1_id else match.team1_id
            winner_row = rows[match.winner_team_id]
            loser_row = rows[loser_team_id]
            winner_row["points"] += 3
            winner_row["series_wins"] += 1
            winner_row["series_diff"] += 1
            winner_row["room_diff"] += match.team1_room_wins - match.team2_room_wins if match.winner_team_id == match.team1_id else match.team2_room_wins - match.team1_room_wins
            loser_row["series_losses"] += 1
            loser_row["series_diff"] -= 1
            loser_row["room_diff"] += match.team1_room_wins - match.team2_room_wins if loser_team_id == match.team1_id else match.team2_room_wins - match.team1_room_wins
            direct_results[(match.winner_team_id, loser_team_id)] = direct_results.get((match.winner_team_id, loser_team_id), 0) + 1

        standings: dict[str, list[dict]] = {}
        for group_label, rows in rows_by_group.items():
            ordered = sorted(
                rows.values(),
                key=lambda row: (
                    -row["points"],
                    -row["series_diff"],
                    -row["room_diff"],
                    row["registered_at"],
                    row["team_id"],
                ),
            )
            standings[group_label] = self._apply_two_team_head_to_head(ordered, direct_results)
        return standings

    def _apply_two_team_head_to_head(self, ordered: list[dict], direct_results: dict[tuple[int, int], int]) -> list[dict]:
        if len(ordered) < 2:
            return ordered
        adjusted = list(ordered)
        index = 0
        while index < len(adjusted) - 1:
            current = adjusted[index]
            nxt = adjusted[index + 1]
            if (
                current["points"] == nxt["points"]
                and current["series_diff"] == nxt["series_diff"]
                and current["room_diff"] == nxt["room_diff"]
            ):
                if direct_results.get((nxt["team_id"], current["team_id"]), 0) > direct_results.get((current["team_id"], nxt["team_id"]), 0):
                    adjusted[index], adjusted[index + 1] = adjusted[index + 1], adjusted[index]
            index += 1
        return adjusted
