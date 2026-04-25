# Pterodactyl Deployment

Highlight Manger is supported on Pterodactyl with the Season 2 runtime.

## Required Environment

- `DISCORD_TOKEN`
- `DATABASE_URL`
- `DISCORD_GUILD_ID`
- `DEFAULT_PREFIX`

Recommended optional variables:

- `DISCORD_CLIENT_ID`
- `LOG_LEVEL=INFO`
- `QUEUE_TIMEOUT_SECONDS=300`
- `ROOM_INFO_TIMEOUT_SECONDS=60`
- `RESULT_TIMEOUT_SECONDS=1800`
- `RECOVERY_INTERVAL_SECONDS=5`
- `CLEANUP_INTERVAL_SECONDS=30`
- `RESULT_CHANNEL_DELETE_DELAY_SECONDS=600`
- `EMERGENCY_COIN_ADJUSTMENTS_ENABLED=false`

For the full Season 2 launch gate, use:

- `deploy/season2-launch-readiness.md`

## Migration Gate

Before launching or restarting against production data, apply and verify migrations:

```bash
alembic upgrade head
alembic current
```

## Startup Command

Use this as the startup command:

```bash
/bin/bash -lc "if [[ -d .git ]] && [[ \"${AUTO_UPDATE}\" == \"1\" ]]; then git pull; fi; /usr/local/bin/python -m pip install -U -r requirements.txt; exec /usr/local/bin/python -u app.py"
```

## Startup Variables

- `PY_FILE=app.py`
- `REQUIREMENTS_FILE=requirements.txt`
- `AUTO_UPDATE=1`

## Discord Checklist

- `MESSAGE CONTENT INTENT` enabled
- `SERVER MEMBERS INTENT` enabled
- invite includes `bot` and `applications.commands`

## Voice Checklist

- `PyNaCl` and `davey` installed from `requirements.txt`
- bot has `View Channel` and `Connect` on the selected persistent voice
- bot has `Move Members` for queue->match voice moves

## Expected Healthy Startup

Look for these log events:

- `app_commands_synced`
- `startup_health`
- `bot_ready`
- `persistent_voice_connected`

If persistent voice does not connect, check:

- `/admin bot-voice-status`
- selected voice channel still exists
- permissions are present
- `PyNaCl` and `davey` installed successfully during startup
