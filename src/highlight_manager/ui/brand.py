from __future__ import annotations

from pathlib import Path

import discord


BRAND_NAME = "HIGHLIGHT MANGER"
BRAND_TAGLINE = "Serious Competitive Ranked Platform"
BRAND_FOOTER = f"{BRAND_NAME}  •  {BRAND_TAGLINE}"

ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "brand"
LOGO_FILENAME = "highlight-logo.gif"
BANNER_FILENAME = "highlight-banner.gif"
RED_LOGO_FILENAME = "highlight-red-logo.gif"

LOGO_ATTACHMENT_URL = f"attachment://{LOGO_FILENAME}"
BANNER_ATTACHMENT_URL = f"attachment://{BANNER_FILENAME}"
RED_LOGO_ATTACHMENT_URL = f"attachment://{RED_LOGO_FILENAME}"


def apply_embed_chrome(
    embed: discord.Embed,
    *,
    section: str | None = None,
    footer: str | None = None,
) -> discord.Embed:
    """Apply consistent non-attachment brand chrome to an embed."""
    embed.set_author(name=BRAND_NAME)
    footer_text = footer or (f"{BRAND_NAME}  •  {section}" if section else BRAND_FOOTER)
    embed.set_footer(text=footer_text)
    return embed


def apply_asset_branding(
    embed: discord.Embed,
    *,
    banner: bool = False,
    red_logo: bool = False,
) -> list[discord.File]:
    """Attach local GIF brand assets and point the embed at them."""
    logo_filename = RED_LOGO_FILENAME if red_logo else LOGO_FILENAME
    logo_url = RED_LOGO_ATTACHMENT_URL if red_logo else LOGO_ATTACHMENT_URL
    embed.set_thumbnail(url=logo_url)
    files = [discord.File(ASSET_DIR / logo_filename, filename=logo_filename)]
    if banner:
        embed.set_image(url=BANNER_ATTACHMENT_URL)
        files.append(discord.File(ASSET_DIR / BANNER_FILENAME, filename=BANNER_FILENAME))
    return files


def brand_asset_paths() -> tuple[Path, Path, Path]:
    return (
        ASSET_DIR / LOGO_FILENAME,
        ASSET_DIR / BANNER_FILENAME,
        ASSET_DIR / RED_LOGO_FILENAME,
    )
