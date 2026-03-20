# Production Notes

## Ubuntu VPS Checklist

1. Install Python 3.11+ and create a virtualenv.
2. Put Discord and MongoDB secrets into `.env`.
3. Install dependencies with `pip install -r requirements.txt` or `pip install -e .`.
4. Make sure the bot role is above `Mvp` and `Professional Highlight Player`.
5. Give the bot these Discord permissions:
   - View Channels
   - Send Messages
   - Read Message History
   - Embed Links
   - Manage Channels
   - Move Members
   - Manage Roles
   - Manage Nicknames
   - Use Application Commands
6. Keep the configured Apostado and Highlight play rooms available. `!play` is blocked everywhere else.
7. Keep the configured Waiting Voice available. Match creation and joining depend on it.
8. `Rank 0` is a manual staff override only. Use `/rank0 grant` and `/rank0 revoke` instead of editing player nicknames by hand.
9. Room details are private by design. The creator or staff submits them through **Enter Room Info**, and the bot posts the details in the private match room only.

## Startup Behavior

On boot the bot:

- validates environment settings
- pings MongoDB before continuing
- syncs prefix and slash commands
- restores active queue, result, and room-info views
- finishes matches that were stuck in `FULL`
- recreates missing result rooms for active matches when possible
- processes persisted queue, vote, and cleanup deadlines immediately
- removes stale temporary team voices from closed matches
- keeps `!play` restricted to the configured Apostado and Highlight play rooms
- recalculates ranks as live seasonal placement using points, wins, winner MVPs, join date, and user ID
- preserves manual `Rank 0` members outside the normal placement ladder
- keeps nicknames in the required `Rank X UserName` format whenever placement changes
- keeps the permanent `Mvp` achievement role synced when players reach the configured thresholds
- can announce match creation and match-ready states with configurable `@here` pings

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
2. Pull the latest code.
3. Refresh the virtualenv dependencies if needed.
4. Start the service again.
5. Check logs for `startup_initializing`, `bot_setup_complete`, and `bot_ready`.
6. Verify after deploy:
   - `/config` shows the expected play rooms and match announcement settings
   - `!leaderboard` opens the paginated leaderboard UI
   - `/rank0 grant` and `/rank0 revoke` behave correctly
   - a full test match can submit room details privately through **Enter Room Info**
