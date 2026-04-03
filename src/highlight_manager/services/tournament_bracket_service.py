from __future__ import annotations

import random
from collections.abc import Iterable
from itertools import combinations

from highlight_manager.models.enums import TournamentSize
from highlight_manager.models.tournament import TournamentTeam
from highlight_manager.utils.exceptions import UserFacingError


class TournamentBracketService:
    def get_preset(self, size: TournamentSize) -> dict[str, int]:
        presets = {
            TournamentSize.SMALL: {"max_teams": 8, "group_count": 2, "advancing_per_group": 2},
            TournamentSize.MEDIUM: {"max_teams": 16, "group_count": 4, "advancing_per_group": 2},
            TournamentSize.HUGE: {"max_teams": 32, "group_count": 8, "advancing_per_group": 2},
        }
        return presets[size]

    def assign_groups(self, teams: list[TournamentTeam], group_count: int) -> dict[str, list[TournamentTeam]]:
        shuffled = list(teams)
        random.SystemRandom().shuffle(shuffled)
        groups = {label: [] for label in self.group_labels(group_count)}
        for index, team in enumerate(shuffled):
            label = self.group_labels(group_count)[index % group_count]
            groups[label].append(team)
        return groups

    def build_group_pairings(self, groups: dict[str, list[TournamentTeam]]) -> list[tuple[str, int, int, str]]:
        pairings: list[tuple[str, int, int, str]] = []
        for label, teams in groups.items():
            for team1, team2 in combinations(teams, 2):
                pairings.append((label, team1.team_number, team2.team_number, "Group Stage"))
        return pairings

    def seed_knockout(
        self,
        size: TournamentSize,
        qualified_teams: dict[str, list[TournamentTeam]],
    ) -> tuple[str, list[tuple[int, int]]]:
        random_qualified = [team for teams in qualified_teams.values() for team in teams]
        random.SystemRandom().shuffle(random_qualified)
        if size == TournamentSize.SMALL:
            return "Semifinal", self._random_pairs(random_qualified)
        if size == TournamentSize.MEDIUM:
            return "Quarterfinal", self._random_pairs(random_qualified)
        return "Round of 16", self._random_pairs(random_qualified)

    def build_next_round(self, winner_team_ids: Iterable[int]) -> tuple[str, list[tuple[int, int]]]:
        winners = list(winner_team_ids)
        if len(winners) < 2 or len(winners) % 2 != 0:
            raise UserFacingError("Could not build the next tournament round from the current winners.")
        round_label = {
            8: "Quarterfinal",
            4: "Semifinal",
            2: "Final",
        }.get(len(winners), f"Round of {len(winners)}")
        return round_label, [(winners[index], winners[index + 1]) for index in range(0, len(winners), 2)]

    def group_labels(self, count: int) -> list[str]:
        return [chr(ord("A") + index) for index in range(count)]

    def _require_pairs(
        self,
        qualified_teams: dict[str, list[TournamentTeam]],
        rules: list[tuple[str, int, str, int]],
    ) -> list[tuple[int, int]]:
        pairs: list[tuple[int, int]] = []
        for left_group, left_index, right_group, right_index in rules:
            try:
                left_team = qualified_teams[left_group][left_index]
                right_team = qualified_teams[right_group][right_index]
            except (KeyError, IndexError) as exc:
                raise UserFacingError("Qualified teams are incomplete for knockout seeding.") from exc
            pairs.append((left_team.team_number, right_team.team_number))
        return pairs

    def _random_pairs(self, teams: list[TournamentTeam]) -> list[tuple[int, int]]:
        if len(teams) < 2 or len(teams) % 2 != 0:
            raise UserFacingError("Qualified teams are incomplete for knockout seeding.")
        return [(teams[index].team_number, teams[index + 1].team_number) for index in range(0, len(teams), 2)]
