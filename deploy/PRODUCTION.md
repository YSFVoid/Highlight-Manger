# Production Notes

## Ubuntu VPS Checklist

1. Install Python 3.11+ and create a virtualenv.
2. Install MongoDB access credentials and Discord bot secrets into `.env`.
3. Install dependencies with `pip install -r requirements.txt` or `pip install -e .`.
4. Ensure the bot role is above the `Professional Highlight Player` reward role and can:
   - Manage Channels
   - Move Members
   - Manage Roles
   - View Channels
   - Send Messages
   - Read Message History
   - Embed Links
   - Use Application Commands
5. `Manage Nicknames` is recommended for automatic `Rank X UserName` renames but setup now continues without it.
6. Configure or keep the setup-created `apostado-play` and `highlight-play` text channels, because `!play` is blocked outside the configured play rooms.

## Startup Behavior

On boot the bot now:

- validates and loads environment settings
- pings MongoDB before continuing
- syncs prefix and slash commands
- restores active queue and voting views
- finishes matches that were stuck in `FULL`
- recreates missing result channels for active matches when possible
- processes persisted queue, vote, and result cleanup deadlines immediately
- removes stale team voice channels from already-closed matches
- keeps `!play` restricted to the configured Apostado and Highlight play rooms after config is loaded

## systemd Deployment

1. Copy `deploy/systemd/highlight-manager.service` to `/etc/systemd/system/highlight-manager.service`.
2. Adjust `User`, `WorkingDirectory`, `EnvironmentFile`, and `ExecStart`.
3. Run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable highlight-manager
sudo systemctl restart highlight-manager
sudo journalctl -u highlight-manager -f
```

## Safe Upgrade Flow

1. Stop the service.
2. Pull or copy the updated code.
3. Refresh the virtualenv dependencies if needed.
4. Start the service again.
5. Check logs for `startup_initializing`, `bot_setup_complete`, and `bot_ready`.
