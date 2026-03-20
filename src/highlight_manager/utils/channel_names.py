from __future__ import annotations

from highlight_manager.models.match import MatchRecord


_BOLD_TRANSLATION = str.maketrans(
    {
        **{chr(ord("A") + index): chr(ord("𝐀") + index) for index in range(26)},
        **{chr(ord("a") + index): chr(ord("𝐚") + index) for index in range(26)},
        **{str(index): chr(ord("𝟎") + index) for index in range(10)},
    }
)


def to_bold_channel_text(value: str) -> str:
    return value.translate(_BOLD_TRANSLATION)


def build_match_name_context(match: MatchRecord) -> dict[str, str | int]:
    match_type_upper = match.match_type.label.upper()
    return {
        "match_id": match.display_id,
        "match_id_styled": to_bold_channel_text(match.display_id),
        "match_number": match.match_number,
        "match_number_styled": to_bold_channel_text(str(match.match_number)),
        "match_type": match.match_type.label,
        "match_type_upper": match_type_upper,
        "match_type_styled": to_bold_channel_text(match_type_upper),
        "mode": match.mode.value,
        "mode_styled": to_bold_channel_text(match.mode.value.upper()),
        "team1_label": "TEAM 1",
        "team2_label": "TEAM 2",
        "team1_label_styled": to_bold_channel_text("TEAM 1"),
        "team2_label_styled": to_bold_channel_text("TEAM 2"),
        "result_label_styled": to_bold_channel_text("RESULT"),
    }


def format_match_channel_name(template: str, match: MatchRecord) -> str:
    return template.format(**build_match_name_context(match))
