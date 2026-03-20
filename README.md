# Highlight Manager

Highlight Manager is a production-minded Discord bot for a single Free Fire server. It manages ranked Apostado and Highlight matches, waiting voice validation, auto-created team voices, private result channels, player voting, points, ranks, blacklists, and seasons.

Ranks are stored internally in MongoDB and synced to nicknames as `Rank X UserName`. The bot does not use Discord rank roles. The only Discord reward role is the seasonal top-5 role: `Professional Highlight Player`.

## Stack

- Python 3.11+
- `discord.py`
- MongoDB with PyMongo async API
- Pydantic v2
- `pydantic-settings`
- `python-dotenv`
- `structlog`

## What It Does

- Member prefix commands for gameplay:
  - `!play <mode> <type>`
  - `!profile`
  - `!rank`
  - `!leaderboard`
  - `!top`
  - `!stats [user]`
- Admin slash commands for setup and moderation:
  - `/setup`
  - `/bootstrap preview`
  - `/bootstrap rerun`
  - `/config`
  - `/season start`
  - `/season end`
  - `/rank set`
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

## Core Flow

1. Player joins the configured Waiting Voice.
2. Player runs `!play 2v2 apos`, `!play 4v4 high`, and similar variants in the configured Apostado or Highlight play room.
3. Bot creates the public match queue embed with buttons.
4. Players join teams through buttons.
5. When the queue fills, the bot:
   - creates `TEAM 1` and `TEAM 2` temporary voice channels
   - moves players into team voices
   - creates a private result channel named like `match-001-result`
   - opens vote flow and starts the voting deadline
6. Players submit result votes in the result channel.
7. When consensus is valid, the bot finalizes the match, updates points/ranks, posts the summary, and cleans resources.
8. If queue fill or vote reporting times out, the bot persists the failure state, applies the configured penalties, and cleans up safely.

## Project Structure

```text
src/highlight_manager/
  bot.py
  commands/
    prefix/gameplay.py
    slash/admin.py
  config/
    logging.py
    settings.py
  interactions/
    views.py
  models/
  repositories/
  services/
  utils/
tests/
deploy/
  systemd/highlight-manager.service
  supervisor/highlight-manager.conf
```

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
```

Update `.env` with your bot token, client ID, and MongoDB URI.

If you prefer plain requirements files for VPS automation:

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

## Production Run

### systemd

Copy [highlight-manager.service](deploy/systemd/highlight-manager.service) to `/etc/systemd/system/highlight-manager.service`, adjust paths/user, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable highlight-manager
sudo systemctl start highlight-manager
sudo systemctl status highlight-manager
```

### Supervisor

Use [highlight-manager.conf](deploy/supervisor/highlight-manager.conf) inside your Supervisor config directory, adjust paths/user, then:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl status highlight-manager
```

### Pterodactyl

If you are hosting inside a Pterodactyl Python server, upload this repo and use:

```bash
bash /home/container/start.sh
```

Then set the required environment variables in the panel Startup or Environment section. Full panel-specific notes are in [deploy/PTERODACTYL.md](deploy/PTERODACTYL.md).

## Setup Guide

1. Invite the bot with the permissions listed below.
2. Run `/setup` and optionally provide a prefix.
3. The bot automatically reuses or creates:
   - `apostado-play`
   - `highlight-play`
   - Waiting Voice
   - temp match voice category
   - results category
   - logs channel
   - `Professional Highlight Player` reward role when auto-create is enabled
4. On the first successful setup, the bot runs a one-time bootstrap for current members:
   - assigns starting rank by server age
   - assigns aligned starting points
   - saves the internal rank in the database
   - attempts nickname sync for every eligible processed member using `Rank X UserName`
   - reports rename outcomes separately for renamed members, already-correct nicknames, hierarchy skips, missing-permission skips, and other rename failures
5. Use `/setup action:status` to inspect saved setup state.
6. Use `/setup action:repair` to repair missing resources safely.
7. Use `/bootstrap preview` and `/bootstrap rerun` for maintenance.
8. Use `/config` later for additional manual adjustments.

## Permissions Required

- View Channels
- Send Messages
- Read Message History
- Embed Links
- Connect
- Move Members
- Manage Channels
- Use Application Commands
- Manage Roles for the seasonal `Professional Highlight Player` reward role
- Manage Nicknames recommended for automatic rename sync, but setup no longer hard-fails if it is missing

## Data Stored

- Guild config
- Player profiles
- Matches
- Match votes
- Seasons
- Audit logs

## Startup and Recovery

On startup the bot:

- validates settings
- pings and connects to MongoDB
- ensures Mongo indexes
- loads commands
- syncs slash commands
- reconciles active matches
- resumes matches that were stuck in `FULL`
- recreates missing result channels for active matches when possible
- processes due queue, vote, and result cleanup events immediately
- cleans stale team voice channels from already-closed matches
- restores persistent button views
- resumes polling for queue and vote deadlines
- keeps ongoing rank nickname sync active through the normal rank-update path

Timeouts are persisted in MongoDB and polled from storage, so the bot does not rely only on in-memory timers.

## Automated Validation

Run:

```bash
ruff check src tests
pytest -q
python -m compileall src
```

## Manual Verification Checklist

1. New member joins and receives a profile, default lowest internal rank, and nickname sync when possible.
2. First `/setup` creates or reuses all required resources automatically.
3. First `/setup` bootstraps existing members by server age and renames them to `Rank X UserName`.
4. `/setup action:status` shows configured resources and stored IDs.
5. `/setup action:repair` repairs missing resources without duplicating existing ones.
6. Member outside Waiting Voice is blocked from `!play`.
7. Member using `!play 2v2 apos` outside the configured Apostado play room is blocked with a clear message.
8. Member inside Waiting Voice creates `!play 2v2 apos` in the configured play room.
9. Team buttons fill both teams.
10. TEAM 1 and TEAM 2 voice channels are created.
11. Players are moved into the correct temporary voices.
12. Private result channel is created and only players/staff can see it.
13. The private result channel name follows `match-001-result`.
14. Players submit votes and consensus finalizes correctly.
15. Result summary shows old balance, delta, and new balance.
16. Points, internal rank, and nicknames update automatically when rank changes, without any rank-role sync.
17. Bootstrap summary clearly reports rename failures for hierarchy, missing permissions, and other causes.
18. Ending a season assigns `Professional Highlight Player` to the top 5 seasonal players and removes it from old holders who fell out of the top 5.
19. An open queue expires after 5 minutes.
20. An unresolved active match expires after 30 minutes and applies penalties.
21. Restart the bot during an active match and confirm buttons, result room recovery, and timers recover.
22. Staff-only slash commands reject non-staff users.

## Troubleshooting

- If `!play` says setup is missing, run `/setup` or `/config` and ensure Waiting Voice plus temp voice category exist.
- If `!play` is rejected in the wrong room, use it in the configured Apostado or Highlight play channel shown in `/setup status` or `/config`.
- If setup bootstrap reports rename hierarchy skips, move the bot's highest role above the member's highest role.
- If setup bootstrap reports rename missing-permission skips, grant the bot `Manage Nicknames`.
- If a member already has the correct `Rank X UserName` nickname, bootstrap reports that separately instead of counting it as a hidden success or silent skip.
- If players are not moved, verify `Move Members`, `Connect`, and `Manage Channels`.
- If the seasonal `Professional Highlight Player` reward is not updating, verify `Manage Roles` and ensure the bot role is above that reward role.
- If slash commands appear late globally, set `DISCORD_GUILD_ID` for faster guild sync during development.
- If MongoDB connection fails, verify the URI, network allowlist, and database user permissions.
- For VPS deployment notes, see [deploy/PRODUCTION.md](deploy/PRODUCTION.md).

## Notes for v2

Potential future improvements:

- richer slash config subcommands for point/rank rule editing
- better stale-resource cleanup heuristics on startup
- more advanced admin review workflows for conflicting votes
- richer audit exports and dashboarding
