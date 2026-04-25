from __future__ import annotations

import discord

from highlight_manager.ui.brand import apply_asset_branding, apply_embed_chrome, brand_asset_paths
from highlight_manager.ui.embeds import build_notice_embed


def test_brand_assets_are_bundled() -> None:
    for path in brand_asset_paths():
        assert path.exists()
        assert path.suffix == ".gif"
        assert path.stat().st_size > 0


def test_embed_chrome_adds_highlight_branding() -> None:
    embed = apply_embed_chrome(discord.Embed(title="Test"), section="Queue")

    assert embed.author.name == "HIGHLIGHT MANGER"
    assert embed.footer.text == "HIGHLIGHT MANGER  •  Queue"


def test_asset_branding_adds_logo_and_banner_attachments() -> None:
    embed = build_notice_embed("Ready", "Live competitive UI.")
    files = apply_asset_branding(embed, banner=True)

    assert embed.thumbnail.url == "attachment://highlight-logo.gif"
    assert embed.image.url == "attachment://highlight-banner.gif"
    assert [file.filename for file in files] == ["highlight-logo.gif", "highlight-banner.gif"]


def test_asset_branding_can_use_red_logo_for_error_style() -> None:
    embed = build_notice_embed("Blocked", "Something failed.", error=True)
    files = apply_asset_branding(embed, red_logo=True)

    assert embed.thumbnail.url == "attachment://highlight-red-logo.gif"
    assert [file.filename for file in files] == ["highlight-red-logo.gif"]
