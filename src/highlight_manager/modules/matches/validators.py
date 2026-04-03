from __future__ import annotations

from highlight_manager.modules.common.exceptions import ValidationError


def validate_team_number(team_number: int) -> None:
    if team_number not in {1, 2}:
        raise ValidationError("Team number must be 1 or 2.")
