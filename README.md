# Highlight Manger

Highlight Manger is the Season 2 production runtime for a competitive Discord server. It manages ranked queues, room-info-before-match conversion, official match lifecycle, rank progression, coins, shop, tournaments, moderation, restart recovery, and persistent bot voice.

## Stack

- Python 3.11+
- `discord.py`
- PostgreSQL / Supabase Postgres
- SQLAlchemy async
- Pydantic v2
- `structlog`
- `PyNaCl` for voice support
- Pillow for card rendering

## Runtime Contract

Use exactly one supported startup path:

```bash
python app.py
```

Required environment variables:

- `DISCORD_TOKEN`
- `DATABASE_URL`
- `DISCORD_GUILD_ID`
- `DEFAULT_PREFIX`

Important Discord application settings:

- `MESSAGE CONTENT INTENT` enabled
- `SERVER MEMBERS INTENT` enabled
- Bot invite includes `bot` and `applications.commands`

## Canonical Architecture

The supported Season 2 runtime is:

- `app.py`
- `src/highlight_manager/app/`
- `src/highlight_manager/db/`
- `src/highlight_manager/modules/`
- `src/highlight_manager/tasks/`
- `src/highlight_manager/ui/`

The older Mongo-style trees under `src/highlight_manager/commands`, `services`, `repositories`, `models`, `interactions`, `jobs`, and `utils` are kept only for legacy reference while Phase 2 cleanup continues. They are not the production source of truth.

For a full layout overview, see [ARCHITECTURE.md](ARCHITECTURE.md).

## Core Member Commands

- `!help`
- `!latestupdate`
- `!play <mode> <ruleset>`
- `!profile`
- `!rank`
- `!leaderboard`
- `!coins`
- `!shop`
- `!tournament`

## Core Staff Commands

- `/admin set-bot-voice`
- `/admin disable-bot-voice`
- `/admin bot-voice-status`
- `/admin system-status`
- `/admin set-apostado-channels`
- `/admin set-highlight-channels`
- `/admin set-esport-channels`
- `/admin set-waiting-voice-channels`
- `/admin rename-members`
- `/match force-close`
- `/match force-result`
- `/season next`

## Match Flow

1. A player runs `!play <mode> <ruleset>`.
2. The queue opens and players join teams using buttons.
3. When the queue fills, the host must submit:
   - `Room ID`
   - `Password`
   - `Key (Optional)`
4. Only after room info is submitted does the bot create the official match.
5. The bot creates result resources, moves waiting players when possible, pings `@here`, and opens result voting.
6. Votes confirm the result, then rank and coins update transactionally.

## Local Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -U -r requirements.txt
copy .env.example .env
python app.py
```

## Linux / VPS Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U -r requirements.txt
cp .env.example .env
python app.py
```

Voice support requires `PyNaCl`, which is already listed in `requirements.txt`.

## Pterodactyl

Use the guide in [deploy/pterodactyl.md](deploy/pterodactyl.md).

Recommended startup command:

```bash
/bin/bash -lc "if [[ -d .git ]] && [[ \"${AUTO_UPDATE}\" == \"1\" ]]; then git pull; fi; /usr/local/bin/python -m pip install -U -r requirements.txt; exec /usr/local/bin/python -u app.py"
```

## systemd

Copy [deploy/systemd/highlight-manager.service](deploy/systemd/highlight-manager.service) to `/etc/systemd/system/highlight-manager.service`, adjust paths/user, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable highlight-manager
sudo systemctl restart highlight-manager
sudo systemctl status highlight-manager
```

## Supervisor

Use [deploy/supervisor/highlight-manager.conf](deploy/supervisor/highlight-manager.conf), adjust paths, then:

```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl restart highlight-manager
```

## Recovery And Stability Notes

- Queue, match, and vote deadlines are DB-driven.
- Button and modal handlers acknowledge early to avoid Discord interaction timeouts.
- Card UI stays enabled; rendering is warmed and cached for production.
- Persistent voice tracks explicit runtime status and retry reason.
- `/admin system-status` surfaces sync state, active queues, active matches, cleanup state, and recovery backlog.

## Validation

```bash
python -m pytest -q
python -m compileall src
```
