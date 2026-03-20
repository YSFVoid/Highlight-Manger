# Pterodactyl Deployment

## Recommended Server Type

Use a Python 3.11+ server/egg.

This bot does not need inbound ports. It only needs outbound internet access so it can:

- connect to Discord
- connect to MongoDB Atlas or your MongoDB server

## Files

Upload the repository contents or pull the GitHub repository into the server root so these files exist in `/home/container`:

- `start.sh`
- `pyproject.toml`
- `requirements.txt`
- `src/`

## Startup Command

Set the Pterodactyl startup command to:

```bash
bash /home/container/start.sh
```

The startup script will:

1. install or refresh Python dependencies when requirements change
2. install the bot package from the repo
3. start `highlight_manager`

## Environment Variables

Set these in the panel Startup or Environment section:

- `DISCORD_TOKEN`
- `DISCORD_CLIENT_ID`
- `MONGODB_URI`
- `MONGODB_DATABASE`
- `DEFAULT_PREFIX`
- `LOG_LEVEL`
- `POLL_INTERVAL_SECONDS`
- `RESULT_CHANNEL_DELETE_DELAY_SECONDS`

Optional:

- `DISCORD_GUILD_ID`

Recommended values:

```text
MONGODB_DATABASE=highlight_manager
DEFAULT_PREFIX=!
LOG_LEVEL=INFO
POLL_INTERVAL_SECONDS=20
RESULT_CHANNEL_DELETE_DELAY_SECONDS=600
```

## First Boot Checklist

1. Confirm the server uses Python 3.11 or newer.
2. Upload the repo or clone it into the container root.
3. Set the startup command to `bash /home/container/start.sh`.
4. Add the environment variables in the panel.
5. Start the server.
6. Watch the console for:
   - `startup_initializing`
   - `bot_setup_complete`
   - `bot_ready`

## Common Offline Causes

If the panel says the server is offline right away, check these first:

1. Wrong startup command.
   Use `bash /home/container/start.sh`.
2. Missing bot files.
   Make sure `src/highlight_manager` exists in the container.
3. Missing environment variables.
   At minimum `DISCORD_TOKEN` and `MONGODB_URI` must be set.
4. Unsupported Python version.
   Use Python 3.11+.
5. MongoDB network blocking.
   If you use Atlas, allow the VPS IP or the panel node IP in the Atlas IP allowlist.
6. Invalid Discord token.
   The bot exits during login if the token is wrong or revoked.

## Updating Later

1. Pull the latest repo changes or upload the updated files.
2. Restart the server.
3. `start.sh` will reinstall dependencies automatically when `requirements.txt` or `pyproject.toml` changes.
