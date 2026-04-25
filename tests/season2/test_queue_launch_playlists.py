from __future__ import annotations

from types import SimpleNamespace

import pytest

from highlight_manager.app.bot import (
    HighlightBot,
    LAUNCH_RANKED_PLAYLISTS,
    launch_ranked_playlist_label,
    launch_ranked_playlist_summary,
)
from highlight_manager.modules.common.enums import MatchMode, RulesetKey
from highlight_manager.modules.common.exceptions import ValidationError


def _settings():
    return SimpleNamespace(
        apostado_channel_ids=None,
        highlight_channel_ids=None,
        esport_channel_ids=None,
    )


def test_launch_ranked_playlists_match_season_two_queue_rules() -> None:
    expected = {
        (MatchMode.ONE_V_ONE, RulesetKey.APOSTADO),
        (MatchMode.TWO_V_TWO, RulesetKey.APOSTADO),
        (MatchMode.THREE_V_THREE, RulesetKey.APOSTADO),
        (MatchMode.FOUR_V_FOUR, RulesetKey.APOSTADO),
        (MatchMode.ONE_V_ONE, RulesetKey.HIGHLIGHT),
        (MatchMode.TWO_V_TWO, RulesetKey.HIGHLIGHT),
        (MatchMode.THREE_V_THREE, RulesetKey.HIGHLIGHT),
        (MatchMode.FOUR_V_FOUR, RulesetKey.HIGHLIGHT),
        (MatchMode.FOUR_V_FOUR, RulesetKey.ESPORT),
        (MatchMode.SIX_V_SIX, RulesetKey.ESPORT),
    }

    assert set(LAUNCH_RANKED_PLAYLISTS) == expected


def test_ranked_queue_validation_uses_launch_playlist_matrix() -> None:
    bot = object.__new__(HighlightBot)
    settings = _settings()

    for mode, ruleset in LAUNCH_RANKED_PLAYLISTS:
        HighlightBot.validate_ranked_queue_request(
            bot,
            settings,
            mode=mode,
            ruleset=ruleset,
            source_channel_id=None,
        )

    with pytest.raises(ValidationError, match="Esport queues only support 4v4 or 6v6"):
        HighlightBot.validate_ranked_queue_request(
            bot,
            settings,
            mode=MatchMode.TWO_V_TWO,
            ruleset=RulesetKey.ESPORT,
            source_channel_id=None,
        )
    with pytest.raises(ValidationError, match="6v6 is only available for the esport ruleset"):
        HighlightBot.validate_ranked_queue_request(
            bot,
            settings,
            mode=MatchMode.SIX_V_SIX,
            ruleset=RulesetKey.HIGHLIGHT,
            source_channel_id=None,
        )


def test_quick_play_picker_exposes_only_launch_playlists() -> None:
    bot = object.__new__(HighlightBot)
    view = HighlightBot.build_play_picker_view(bot)

    labels = [item.label for item in view.children]
    expected_labels = [launch_ranked_playlist_label(mode, ruleset) for mode, ruleset in LAUNCH_RANKED_PLAYLISTS]

    assert labels == expected_labels
    assert "6v6 Apostado" not in labels
    assert "1v1 Esport" not in labels


def test_quick_play_embed_lists_launch_playlists() -> None:
    bot = object.__new__(HighlightBot)
    embed = HighlightBot.build_play_picker_embed(bot, "!")

    assert embed.description is not None
    assert launch_ranked_playlist_summary() in embed.description
    assert "**Apostado:** `1v1`, `2v2`, `3v3`, `4v4`" in embed.description
    assert "**Highlight:** `1v1`, `2v2`, `3v3`, `4v4`" in embed.description
    assert "**Esport:** `4v4`, `6v6`" in embed.description
