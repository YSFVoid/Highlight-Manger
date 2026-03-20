# Highlight Manager

Highlight Manager is a Python Discord bot for one competitive Free Fire server. It manages Apostado and Highlight matches, waiting voice validation, private match result rooms, temporary team voice channels, private room-info sharing, player voting, seasonal points, live placement ranks, blacklist checks, and reward roles.

Ranks are stored internally and synced to nicknames as `Rank X UserName`. Rank is live leaderboard placement, not a fixed tier and not a Discord role. A manual `Rank 0` override is also supported for staff use.

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

## Match Room Info Flow

- When a match becomes ready, the bot can announce it publicly and optionally ping `@here`.
- The creator or staff can press **Enter Room Info** to open a modal.
- The modal collects:
  - Room ID
  - Password
  - Private Match Key
- Room ID must be numeric.
- Password is optional.
- Private Match Key is optional unless the guild config requires it.
- Sensitive room details are only posted in the private match result room, never in the public play room.

## Leaderboard / Profile UI

- `!rank` opens a focused rank overview embed.
- `!profile` and `!stats [user]` open a richer profile card with season and lifetime stats.
- `!leaderboard` and `!top` open a paginated leaderboard with switchable views for:
  - season points
  - season wins
  - season MVP totals

## Default Setup Resources

The bot auto-creates or reuses these resources during `/setup`:

- Apostado play room
- Highlight play room
- Waiting Voice
- Temporary match voice category
- Match results category
- Logs channel
- `Mvp`
- `Professional Highlight Player`

Default channel and category names use stylized Unicode labels. If Discord rejects a stylized name for a resource type, setup falls back cleanly to the ASCII legacy name instead of crashing.

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

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
```

Or for VPS automation:

```bash
pip install -r requirements-dev.txt
```

## Environment Variables

See [.env.example](.env.example).

- `DISCORD_TOKEN`
- `DISCORD_CLIENT_ID`
- `MONGODB_URI`
- `MONGODB_DATABASE`
- `DISCORD_GUILD_ID`
- `DEFAULT_PREFIX`
- `LOG_LEVEL`
- `POLL_INTERVAL_SECONDS`
- `RESULT_CHANNEL_DELETE_DELAY_SECONDS`

## Local Run

```bash
python -m highlight_manager
```

## VPS / Production

### systemd

Copy [highlight-manager.service](deploy/systemd/highlight-manager.service) to `/etc/systemd/system/highlight-manager.service`, adjust paths and user, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable highlight-manager
sudo systemctl restart highlight-manager
sudo journalctl -u highlight-manager -f
```

### Supervisor

Use [highlight-manager.conf](deploy/supervisor/highlight-manager.conf), adjust paths and user, then:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status highlight-manager
```

### Pterodactyl

If you host this bot in a Pterodactyl Python server:

```bash
bash /home/container/start.sh
```

Full panel notes are in [deploy/PTERODACTYL.md](deploy/PTERODACTYL.md).

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

## Validation Commands

```bash
ruff check src tests
pytest -q
python -m compileall src
```

## Troubleshooting

- If `!play` is rejected, use the configured Apostado or Highlight play room shown by `/setup status` or `/config`.
- If `!play` says setup is incomplete, run `/setup` or `/setup action:repair`.
- If a match is ready but players cannot see the room details, check the private result room and confirm the creator or staff submitted room info through **Enter Room Info**.
- If `@here` is too noisy or missing, review `ping_here_on_match_create` and `ping_here_on_match_ready` through `/config`.
- If nickname sync fails, check `Manage Nicknames` and role hierarchy.
- If Rank 0 was granted accidentally, use `/rank0 revoke`.
- If waiting-voice enforcement fails, confirm the configured Waiting Voice still exists.
- If the `Mvp` role is not being granted, check `Manage Roles`, bot hierarchy, and the configured MVP thresholds.
- If the season reward role is not updating, check `Manage Roles` and that the bot role is above `Professional Highlight Player`.
- If MongoDB Atlas rejects the connection, allow the VPS or panel node IP in the Atlas allowlist.
