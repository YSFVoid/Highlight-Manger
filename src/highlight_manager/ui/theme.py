from __future__ import annotations

import discord


# ── Brand colors ──────────────────────────────────────────────────────
SURFACE = discord.Colour.from_rgb(22, 23, 31)
PRIMARY = discord.Colour.from_rgb(84, 124, 255)
ACCENT = discord.Colour.from_rgb(146, 98, 255)
SUCCESS = discord.Colour.from_rgb(79, 201, 126)
WARNING = discord.Colour.from_rgb(231, 167, 73)
ERROR = discord.Colour.from_rgb(224, 87, 87)

# ── Tier colors (for embed sidebars) ─────────────────────────────────
TIER_COLORS = {
    "bronze": discord.Colour.from_rgb(122, 91, 58),
    "silver": discord.Colour.from_rgb(167, 182, 200),
    "gold": discord.Colour.from_rgb(216, 169, 59),
    "platinum": discord.Colour.from_rgb(93, 203, 200),
    "diamond": discord.Colour.from_rgb(124, 168, 255),
    "master": discord.Colour.from_rgb(130, 107, 255),
    "elite": discord.Colour.from_rgb(200, 91, 255),
}

# ── Emoji system ─────────────────────────────────────────────────────
EMOJI_TROPHY = "🏆"
EMOJI_SWORD = "⚔️"
EMOJI_SHIELD = "🛡️"
EMOJI_COIN = "🪙"
EMOJI_FIRE = "🔥"
EMOJI_CROWN = "👑"
EMOJI_STAR = "⭐"
EMOJI_LOCK = "🔒"
EMOJI_UNLOCK = "🔓"
EMOJI_CHECK = "✅"
EMOJI_PENDING = "⏳"
EMOJI_UP = "📈"
EMOJI_DOWN = "📉"
EMOJI_DOOR = "🚪"
EMOJI_KEY = "🔑"
EMOJI_BELL = "🔔"
EMOJI_SPARKLE = "✨"
EMOJI_BOOM = "💥"
EMOJI_MEDAL = "🏅"

# ── Progress bar rendering ───────────────────────────────────────────
BAR_FILLED = "▓"
BAR_EMPTY = "░"


def progress_bar(current: int, total: int, *, length: int = 10) -> str:
    """Render a text-based progress bar like ▓▓▓▓▓░░░░░."""
    if total <= 0:
        return BAR_FILLED * length
    filled = int(current / total * length)
    filled = min(filled, length)
    return BAR_FILLED * filled + BAR_EMPTY * (length - filled)


def slot_display(filled: int, total: int) -> str:
    """Render player slot indicators like ●●●○○."""
    return "●" * filled + "○" * (total - filled)

