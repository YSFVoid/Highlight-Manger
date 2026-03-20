# Highlight Manager

Highlight Manager is a Python Discord bot for one competitive Free Fire server. It manages Apostado and Highlight matches, waiting voice validation, private match result rooms, temporary team voice channels, player voting, seasonal points, live placement ranks, blacklist checks, and reward roles.

Ranks are stored internally and synced to nicknames as `Rank X UserName`. Rank is live leaderboard placement, not a fixed tier and not a Discord role.

## Stack

- Python 3.11+
- `discord.py`
- MongoDB with PyMongo async API
- Pydantic v2
- `pydantic-settings`
- `python-dotenv`
- `structlog`

## Member Commands

- `!play <mode> <type>`
- `!profile`
- `!rank`
- `!leaderboard`
- `!top`
- `!stats [user]`

Supported match modes:

- `1v1`
- `2v2`
- `3v3`
- `4v4`

Supported type aliases:

- `apos`
- `apostado`
- `high`
- `highlight`

## Admin Commands

- `/setup`
- `/setup action:status`
- `/setup action:repair`
- `/bootstrap preview`
- `/bootstrap rerun`
- `/config`
- `/season start`
- `/season end`
- `/points add`
- `/points remove`
- `/points set`
- `/match cancel`
- `/match force-result`
- `/match force-close`
- `/blacklist add`
- `/blacklist remove`

## Rank Model

- Rank is live seasonal leaderboard placement.
- Rank 1 means first place, Rank 2 means second place, and so on with no hard cap.
- Tiebreak order is:
  - higher seasonal points
  - higher seasonal wins
  - higher seasonal winner-MVP count
  - older server join date
  - lower user ID as a stable fallback
- Nicknames are always synced as `Rank X UserName`.

## Reward Roles

### `Mvp`

Permanent achievement role.

- awarded once `mvpWinnerCount >= 50`
- or `mvpLoserCount >= 75`
- created during setup if missing
- limited to `Move Members`, `Mute Members`, and `Deafen Members`
- never removed automatically

### `Professional Highlight Player`

Season reward role.

- granted to the configured top seasonal placements when a season ends
- removed from previous holders who are no longer in the configured top group
- default top count is `5`

## Default Setup Resources

The bot auto-creates or reuses these resources during `/setup`:

- `𝗔𝗽𝗼𝘀𝘁𝗮𝗱𝗼-𝗣𝗹𝗮𝘆`
- `𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗣𝗹𝗮𝘆`
- `𝗪𝗮𝗶𝘁𝗶𝗻𝗴-𝗩𝗼𝗶𝗰𝗲`
- `𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗠𝗮𝘁𝗰𝗵-𝗩𝗼𝗶𝗰𝗲𝘀`
- `𝗠𝗮𝘁𝗰𝗵-𝗥𝗲𝘀𝘂𝗹𝘁𝘀`
- `𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗟𝗼𝗴𝘀`
- `Mvp`
- `Professional Highlight Player`

If Discord rejects a stylized Unicode name for a resource type, setup falls back cleanly to the ASCII legacy name instead of crashing.

## Bootstrap Behavior

On the first successful `/setup` only:

1. All non-bot members are sorted by server join date, oldest first.
2. Oldest member gets Rank 1, next gets Rank 2, and so on with no limit.
3. Everyone starts with `0` season points.
4. Everyone is renamed to `Rank X UserName` when permissions allow.
5. Rename results are reported separately for:
   - renamed members
   - already-correct nicknames
   - hierarchy skips
   - missing-permission skips
   - other failures

New members who join later start with `0` points and are assigned the last current rank position by default.

## What Setup Must Validate

- Waiting Voice exists
- temp match voice category exists
- results parent exists
- logs channel exists
- Apostado play room exists
- Highlight play room exists
- `Mvp` role exists
- `Professional Highlight Player` role exists or is reusable

## Startup / Recovery

On startup the bot:

- validates env settings
- connects to MongoDB
- ensures indexes
- syncs slash commands
- reconciles unfinished matches
- restores timeout polling
- recreates missing result rooms when possible
- cleans stale temporary match voices
- restores persistent button views
