from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps


FONT_DIR = Path("C:/Windows/Fonts")
FONT_REGULAR = FONT_DIR / "segoeui.ttf"
FONT_BOLD = FONT_DIR / "segoeuib.ttf"
FONT_TITLE = FONT_DIR / "bahnschrift.ttf"

BG = (9, 10, 14, 255)
PANEL = (24, 26, 34, 235)
PANEL_ALT = (31, 34, 45, 235)
OUTLINE = (255, 255, 255, 24)
TEXT = (244, 244, 248, 255)
MUTED = (162, 170, 184, 255)
PRIMARY = (98, 136, 255, 255)
ACCENT = (168, 101, 255, 255)
SUCCESS = (88, 207, 140, 255)
GOLD = (241, 194, 62, 255)
SILVER = (198, 205, 221, 255)
BRONZE = (212, 144, 91, 255)


@dataclass(slots=True)
class ProfileCardData:
    display_name: str
    season_name: str
    points: int
    wins: int
    losses: int
    matches: int
    winrate_text: str
    rank_text: str
    coins: int
    peak: int
    avatar_bytes: bytes | None = None


@dataclass(slots=True)
class LeaderboardCardEntry:
    rank: int
    display_name: str
    wins: int
    losses: int
    winrate_text: str
    points: int
    avatar_bytes: bytes | None = None


def _buffer_from_image(image: Image.Image) -> BytesIO:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


@lru_cache(maxsize=32)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=size)


def _base_canvas(width: int, height: int) -> Image.Image:
    image = Image.new("RGBA", (width, height), BG)
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((-120, -100, 440, 360), fill=(98, 136, 255, 120))
    draw.ellipse((width - 420, -90, width + 120, 300), fill=(168, 101, 255, 95))
    draw.ellipse((width - 300, height - 280, width + 180, height + 160), fill=(88, 207, 140, 70))
    draw.rectangle((0, height - 180, width, height), fill=(255, 255, 255, 4))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))
    return image


def _rounded_panel(
    image: Image.Image,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int, int] = PANEL,
    outline: tuple[int, int, int, int] = OUTLINE,
    radius: int = 32,
) -> None:
    panel = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)
    image.alpha_composite(panel)


def _divider(draw: ImageDraw.ImageDraw, x1: int, y: int, x2: int) -> None:
    draw.line((x1, y, x2, y), fill=(255, 255, 255, 22), width=2)


def _avatar_circle(size: int, avatar_bytes: bytes | None, fallback_text: str) -> Image.Image:
    if avatar_bytes:
        avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
        avatar = ImageOps.fit(avatar, (size, size), Image.Resampling.LANCZOS)
    else:
        avatar = Image.new("RGBA", (size, size), PRIMARY)
        avatar_draw = ImageDraw.Draw(avatar)
        initials = (fallback_text.strip()[:2] or "HM").upper()
        avatar_draw.text(
            (size // 2, size // 2),
            initials,
            font=_font(str(FONT_BOLD), max(28, size // 3)),
            fill=TEXT,
            anchor="mm",
        )
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    framed = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    framed.paste(avatar, (0, 0), mask)
    ring = Image.new("RGBA", (size + 12, size + 12), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    ring_draw.ellipse((0, 0, size + 11, size + 11), fill=(0, 0, 0, 0), outline=(255, 255, 255, 140), width=4)
    ring.paste(framed, (6, 6), framed)
    return ring


def render_help_banner(prefix: str) -> BytesIO:
    image = _base_canvas(1280, 360)
    _rounded_panel(image, (42, 36, 1238, 324), fill=(22, 24, 32, 220), radius=36)
    draw = ImageDraw.Draw(image)
    draw.text((86, 92), "HIGHLIGHT MANGER", font=_font(str(FONT_TITLE), 54), fill=TEXT)
    draw.text((88, 152), "Competitive Discord match management", font=_font(str(FONT_REGULAR), 24), fill=MUTED)
    draw.text((88, 192), f"Prefix: {prefix}", font=_font(str(FONT_BOLD), 24), fill=PRIMARY)
    pills = [
        f"{prefix}play 4v4 esport",
        f"{prefix}profile",
        f"{prefix}leaderboard",
        f"{prefix}shop",
    ]
    x = 700
    y = 106
    for pill in pills:
        width = 250 if len(pill) < 14 else 300
        draw.rounded_rectangle((x, y, x + width, y + 48), radius=22, fill=(35, 39, 52, 240), outline=(255, 255, 255, 18), width=2)
        draw.text((x + 20, y + 24), pill, font=_font(str(FONT_BOLD), 22), fill=TEXT, anchor="lm")
        y += 58
    _divider(draw, 86, 248, 650)
    draw.text((88, 270), "Fast queues. Clean rank cards. Premium competitive flow.", font=_font(str(FONT_REGULAR), 22), fill=MUTED)
    return _buffer_from_image(image)


def render_profile_card(data: ProfileCardData) -> BytesIO:
    image = _base_canvas(1200, 760)
    _rounded_panel(image, (54, 140, 1146, 688), radius=42)
    draw = ImageDraw.Draw(image)
    avatar = _avatar_circle(152, data.avatar_bytes, data.display_name)
    image.alpha_composite(avatar, (84, 92))
    draw.text((94, 282), data.display_name, font=_font(str(FONT_BOLD), 46), fill=TEXT)
    draw.text((96, 338), data.rank_text, font=_font(str(FONT_REGULAR), 24), fill=MUTED)
    draw.text((894, 110), data.season_name.upper(), font=_font(str(FONT_BOLD), 24), fill=ACCENT)
    _divider(draw, 94, 388, 1100)

    stats = [
        ("POINTS", str(data.points)),
        ("WINS", str(data.wins)),
        ("LOSSES", str(data.losses)),
        ("COINS", str(data.coins)),
        ("MATCHES", str(data.matches)),
        ("PEAK", str(data.peak)),
        ("WINRATE", data.winrate_text),
        ("RANK", data.rank_text.replace("Rank ", "")),
    ]
    start_x = 96
    start_y = 422
    box_w = 232
    box_h = 104
    gap_x = 14
    gap_y = 18
    for index, (label, value) in enumerate(stats):
        row = index // 4
        col = index % 4
        x1 = start_x + col * (box_w + gap_x)
        y1 = start_y + row * (box_h + gap_y)
        x2 = x1 + box_w
        y2 = y1 + box_h
        draw.rounded_rectangle((x1, y1, x2, y2), radius=24, fill=PANEL_ALT, outline=(255, 255, 255, 14), width=2)
        draw.text((x1 + 22, y1 + 26), label, font=_font(str(FONT_REGULAR), 18), fill=MUTED)
        draw.text((x1 + 22, y1 + 70), value, font=_font(str(FONT_BOLD), 34), fill=TEXT)
    return _buffer_from_image(image)


def render_leaderboard_card(season_name: str, total_players: int, entries: list[LeaderboardCardEntry]) -> BytesIO:
    width = 1280
    height = 180 + 76 * max(1, len(entries)) + 70
    image = _base_canvas(width, height)
    _rounded_panel(image, (36, 32, width - 36, height - 36), radius=40)
    draw = ImageDraw.Draw(image)
    draw.text((640, 74), "PLAYER LEADERBOARD", font=_font(str(FONT_TITLE), 46), fill=TEXT, anchor="mm")
    draw.text((640, 120), f"{season_name} | Top {len(entries)} / {total_players} players", font=_font(str(FONT_REGULAR), 22), fill=MUTED, anchor="mm")
    _divider(draw, 88, 152, width - 88)
    draw.text((92, 168), "RANK", font=_font(str(FONT_REGULAR), 18), fill=MUTED)
    draw.text((214, 168), "PLAYER", font=_font(str(FONT_REGULAR), 18), fill=MUTED)
    draw.text((735, 168), "W/L", font=_font(str(FONT_REGULAR), 18), fill=MUTED)
    draw.text((865, 168), "WINRATE", font=_font(str(FONT_REGULAR), 18), fill=MUTED)
    draw.text((1048, 168), "POINTS", font=_font(str(FONT_REGULAR), 18), fill=MUTED)

    start_y = 198
    for index, entry in enumerate(entries):
        y = start_y + index * 76
        row_fill = PANEL_ALT if index % 2 == 0 else (26, 28, 37, 235)
        draw.rounded_rectangle((74, y, width - 74, y + 58), radius=18, fill=row_fill, outline=(255, 255, 255, 10), width=2)
        badge_color = TEXT
        if entry.rank == 1:
            badge_color = GOLD
        elif entry.rank == 2:
            badge_color = SILVER
        elif entry.rank == 3:
            badge_color = BRONZE
        draw.text((120, y + 29), f"#{entry.rank}", font=_font(str(FONT_BOLD), 26), fill=badge_color, anchor="mm")
        avatar = _avatar_circle(42, entry.avatar_bytes, entry.display_name)
        image.alpha_composite(avatar, (166, y + 8))
        draw.text((228, y + 28), entry.display_name, font=_font(str(FONT_BOLD), 24), fill=TEXT)
        draw.text((738, y + 28), f"{entry.wins}/{entry.losses}", font=_font(str(FONT_BOLD), 22), fill=TEXT)
        draw.text((872, y + 28), entry.winrate_text, font=_font(str(FONT_BOLD), 22), fill=PRIMARY)
        pill_left = width - 246
        draw.rounded_rectangle((pill_left, y + 10, width - 100, y + 48), radius=18, fill=(105, 74, 160, 255))
        draw.text((pill_left + 72, y + 29), f"{entry.points:,}", font=_font(str(FONT_BOLD), 24), fill=TEXT, anchor="mm")
    draw.text((width // 2, height - 60), "Highlight Manger competitive standings", font=_font(str(FONT_REGULAR), 18), fill=MUTED, anchor="mm")
    return _buffer_from_image(image)
