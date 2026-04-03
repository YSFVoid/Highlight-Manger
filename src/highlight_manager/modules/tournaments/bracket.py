from __future__ import annotations

from math import ceil, log2


def required_bracket_size(team_count: int) -> int:
    if team_count <= 1:
        return 1
    return 2 ** ceil(log2(team_count))


def seed_pairs(team_ids: list, *, starting_round: int = 1) -> list[tuple[int, int, object | None, object | None]]:
    size = required_bracket_size(len(team_ids))
    padded = list(team_ids) + [None] * (size - len(team_ids))
    pairs: list[tuple[int, int, object | None, object | None]] = []
    position = 1
    while padded:
        team1 = padded.pop(0)
        team2 = padded.pop(-1) if padded else None
        pairs.append((starting_round, position, team1, team2))
        position += 1
    return pairs
