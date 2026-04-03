# Pterodactyl Deployment

Highlight Manger is supported on Pterodactyl with the Season 2 runtime.

## Required Environment

- `DISCORD_TOKEN`
- `DATABASE_URL`
- `DISCORD_GUILD_ID`
- `DEFAULT_PREFIX`

Recommended optional variables:

- `LOG_LEVEL=INFO`
- `RECOVERY_INTERVAL_SECONDS=5`
- `CLEANUP_INTERVAL_SECONDS=30`

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
