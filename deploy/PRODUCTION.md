# Production Notes

## Ubuntu VPS Checklist

1. Install Python 3.11+ and create a virtualenv.
2. Install MongoDB access credentials and Discord bot secrets into `.env`.
3. Install dependencies with `pip install -r requirements.txt` or `pip install -e .`.
4. Ensure the bot role is above both `Mvp` and `Professional Highlight Player`, and that the bot can:
   - Manage Channels
   - Move Members
   - Manage Roles
   - Manage Nicknames
   - View Channels
   - Send Messages
   - Read Message History
   - Embed Links
   - Use Application Commands
5. Keep the setup-created `𝗔𝗽𝗼𝘀𝘁𝗮𝗱𝗼-𝗣𝗹𝗮𝘆` and `𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗣𝗹𝗮𝘆` text channels available, because `!play` is blocked outside the configured play rooms.
6. Default setup resources use stylized Unicode names such as `𝗪𝗮𝗶𝘁𝗶𝗻𝗴-𝗩𝗼𝗶𝗰𝗲`, `𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗠𝗮𝘁𝗰𝗵-𝗩𝗼𝗶𝗰𝗲𝘀`, `𝗠𝗮𝘁𝗰𝗵-𝗥𝗲𝘀𝘂𝗹𝘁𝘀`, and `𝗛𝗶𝗴𝗵𝗹𝗶𝗴𝗵𝘁-𝗟𝗼𝗴𝘀`. If Discord rejects a styled name, setup falls back to the ASCII name and logs the fallback instead of failing.
7. First-time bootstrap assigns placement by server join order only: oldest member becomes `Rank 1`, everyone starts with `0` points, and nickname sync is attempted for every eligible member with explicit reporting for hierarchy and permission skips.

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
- recalculates ranks as live seasonal placement using points, wins, winner MVPs, join date, and user ID as the tiebreak chain
- keeps nicknames in the required `Rank X UserName` format whenever player placement changes
- keeps the permanent `Mvp` achievement role synced when a player reaches the configured MVP thresholds

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
