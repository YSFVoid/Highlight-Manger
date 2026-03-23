# Highlight Manager

Highlight Manager is a Python Discord bot for one competitive Free Fire server. It manages Apostado and Highlight matches, waiting voice validation, private match result rooms, temporary team voice channels, private room-info sharing, player voting, seasonal points, live placement ranks, blacklist checks, reward roles, and polished update announcements.

Ranks are stored internally and synced to nicknames as `RANK X | UserName`. Rank is live leaderboard placement, not a fixed tier and not a Discord role. A manual `Rank 0` override is also supported for staff use.

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
- `!r`
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
- `/waitingvoice add`
- `/waitingvoice remove`
- `/nickname sync-rank`
- `/nickname sync-all`
- `/announce latest-update`
- `/season start`
- `/season end`
- `/rank0 grant`
- `/rank0 revoke`
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
- `Rank 0` is a manual override and is never assigned by normal recalculation.
- Tiebreak order is:
  - higher seasonal points
  - higher seasonal wins
  - higher seasonal winner-MVP count
  - older server join date
  - lower user ID as a stable fallback
- Nicknames are always synced as `RANK X | UserName`.

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

## Match Room Info Flow

- When a member runs `!play`, the bot now posts a room-setup card first instead of opening the public queue immediately.
- The creator or staff presses **Enter Room Info** to open the modal before the queue goes live.
- The modal collects:
  - Room ID
  - Password
  - Private Match Key
- Room ID must be numeric.
- Password is optional.
- Private Match Key is optional unless the guild config requires it.
- After valid room info is submitted, the bot opens the public queue card and can send the configured one-time `@here`.
- Sensitive room details are only posted in the private match result room, never in the public play room.
- The private result room is created up front so room details always have a private delivery surface.
- If the private result room is recreated later, the stored room info is reposted there automatically.

## Match Result Flow

- When a match goes live, the private result room posts a **Choose Winner Team** embed first.
- Only two people can choose the winner team:
  - the match creator
  - the first player who entered Team 2
- Once both captain votes match, the losing team is inferred automatically.
- For team matches, the bot then posts two more private embeds:
  - **Choose Winner MVP**
  - **Choose Loser MVP**
- The winning team captain selects winner MVP.
- The losing team captain selects loser MVP.
- As soon as both MVP selections are recorded, the bot finalizes the match automatically.
- During auto-finalize, the bot:
  - posts the result summary
  - moves players back to Waiting Voice when possible
  - deletes the temporary Team 1 and Team 2 voice channels
  - schedules the private result room for cleanup using the configured delete behavior

## Leaderboard / Profile UI

- `!rank` opens a focused rank overview embed.
- `!profile` and `!stats [user]` open a richer profile card with season and lifetime stats.
- `!leaderboard` and `!top` open a paginated leaderboard with switchable views for:
  - season points
  - season wins
  - season MVP totals
- Match cards, ready cards, room-info cards, and setup/config cards now share one consistent mobile-friendly visual style.

## Default Setup Resources

The bot auto-creates or reuses these resources during `/setup`:

- Apostado play room
- Highlight play room
- Waiting Voice
- Additional waiting voices when needed
- Temporary match voice category
- Match results category
- Logs channel
- `Mvp`
- `Professional Highlight Player`

Default channel and category names use stylized Unicode labels. If Discord rejects a stylized name for a resource type, setup falls back cleanly to the ASCII legacy name instead of crashing.

Configured rooms, voice channels, categories, and reward roles are used by their Discord IDs at runtime. Renaming a configured resource later does not break the bot.

Default live announcement behavior:

- `@here` on queue open: enabled
- `@here` on match ready: disabled

Both can still be changed with `/config`.

## Bootstrap Behavior

On the first successful `/setup` only:

1. All non-bot members are sorted by server join date, oldest first.
2. Oldest member gets Rank 1, next gets Rank 2, and so on with no limit.
3. Everyone starts with `0` season points.
4. Everyone is renamed to `RANK X | UserName` when permissions allow.
5. Rename results are reported separately for:
   - renamed members
   - already-correct nicknames
   - hierarchy skips
   - missing-permission skips
   - other failures

New members who join later start with `0` points and are assigned the last current rank position by default.

## Required Discord Permissions

- View Channels
- Send Messages
- Read Message History
- Embed Links
- Connect
- Move Members
- Manage Channels
- Use Application Commands
- Manage Roles
- Manage Nicknames

## What Setup Must Validate

- Waiting Voice exists
- temp match voice category exists
- results parent exists
- logs channel exists
- Apostado play room exists
- Highlight play room exists
- `Mvp` role exists
- `Professional Highlight Player` role exists or is reusable
- configurable match announcement settings are available
- private room-info flow is available once a match is ready

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
- restores room-info submission views for active matches

## Troubleshooting

- If `!play` is rejected, use the configured Apostado or Highlight play room shown by `/setup status` or `/config`.
- If `!play` says setup is incomplete, run `/setup` or `/setup action:repair`.
- If a match is ready but players cannot see the room details, check the private result room and confirm the creator or staff submitted room info through **Enter Room Info**.
- If `@here` is too noisy or missing, review `ping_here_on_match_create` and `ping_here_on_match_ready` through `/config`.
- If nickname sync fails, check `Manage Nicknames` and role hierarchy.
- If Rank 0 was granted accidentally, use `/rank0 revoke`.
- If waiting-voice enforcement fails, confirm the configured waiting-voice pool still exists and that the correct voice IDs are saved in config.
- If the `Mvp` role is not being granted, check `Manage Roles`, bot hierarchy, and the configured MVP thresholds.
- If the season reward role is not updating, check `Manage Roles` and that the bot role is above `Professional Highlight Player`.
- If MongoDB Atlas rejects the connection, allow the VPS or panel node IP in the Atlas allowlist.
