from __future__ import annotations

import discord

from highlight_manager.interactions.common_views import DismissMessageButton, DismissMessageView, with_dismiss_button
from highlight_manager.utils.response_helpers import build_response_embed


def test_build_response_embed_uses_highlight_manager_title() -> None:
    embed = build_response_embed("Hello world")

    assert embed.title == "Highlight Manager"
    assert embed.description == "Hello world"


def test_with_dismiss_button_creates_dismiss_view_when_missing() -> None:
    view = with_dismiss_button(None, 123)

    assert isinstance(view, DismissMessageView)
    assert any(isinstance(item, DismissMessageButton) for item in view.children)


def test_with_dismiss_button_appends_to_existing_view() -> None:
    view = discord.ui.View()

    updated = with_dismiss_button(view, 123)

    assert updated is view
    assert any(isinstance(item, DismissMessageButton) for item in updated.children)
