# Season 2 Launch Readiness

This is the operational gate for launching Highlight Manger Season 2. Phase 3 is not a
feature phase. Freeze feature work, apply only launch-blocking fixes, and use this file
for deployment readiness, staff operation, monitoring, rehearsal, rollback, and sign-off.

## 1. Deployment Readiness Checklist

Must be complete before launch:

- Freeze feature work. Only launch-blocking fixes are allowed.
- Back up the production Season 2 database.
- Confirm the rollback target: previous deploy artifact or commit, plus access to redeploy it.
- Apply migrations to Alembic head:

```bash
alembic upgrade head
alembic current
```

- Confirm Alembic head includes `20260423_0004_match_ping_targets.py`.
- Run the full Season 2 regression:

```bash
uv run --extra dev pytest tests/season2 -q
```

- Start the bot in the production-like environment and confirm healthy startup logs.
- Confirm command sync, scheduler, cleanup, recovery, diagnostics, and persistent voice status.
- Confirm ranked-pause procedure:
  - Preferred: set the active season `ranked_queue_locked` flag through controlled DB maintenance.
  - Emergency fallback: remove queue-channel send permission and announce ranked pause.

Can wait:

- Non-blocking copy polish.
- Dashboard additions.
- Tournament expansion.
- Shop expansion.

## 2. Environment / Config Verification Checklist

Required:

- `DISCORD_TOKEN` is production.
- `DATABASE_URL` points to the Season 2 PostgreSQL database, not a test database.
- `DEFAULT_PREFIX` is correct.
- `LOG_LEVEL` is `INFO` unless actively debugging.
- `EMERGENCY_COIN_ADJUSTMENTS_ENABLED=false` for launch.
- `QUEUE_TIMEOUT_SECONDS`, `ROOM_INFO_TIMEOUT_SECONDS`, `RESULT_TIMEOUT_SECONDS`,
  `RECOVERY_INTERVAL_SECONDS`, `CLEANUP_INTERVAL_SECONDS`, and
  `RESULT_CHANNEL_DELETE_DELAY_SECONDS` are positive and launch-safe.

Recommended:

- `DISCORD_CLIENT_ID` is set.
- `DISCORD_GUILD_ID` is set when using guild-scoped slash command sync.
- `MONGODB_URI` is empty unless intentionally kept only for legacy inspection.

In Discord/admin config, verify:

- Apostado, Highlight, and Esport queue channel rules.
- Apostado, Highlight, and Esport match ping targets.
- Waiting voice channel list.
- Staff/admin role mappings.
- Persistent bot voice channel.
- Shop storefront channels and launch catalog.

Stop launch if:

- DB migration state is unknown or behind head.
- Emergency coin adjustment is enabled without an active approved correction.
- Queue/rank/economy config points to test values.

## 3. Permissions / Discord Setup Checklist

The bot must have:

- Role position high enough to manage match channels and team voice channels.
- View Channel, Send Messages, Embed Links, Read Message History in launch text channels.
- Manage Channels in the match/result category.
- Connect and Move Members for waiting/team voice flows.
- Access to create private result channels visible only to staff and match participants.
- Slash command access for launch staff/admin roles.

Verify staff/admin commands are visible:

- `/match review-inbox`
- `/match force-result`
- `/match force-close`
- `/match rehost-history`
- `/admin system-status`
- `/admin bot-voice-status`

Investigate immediately if any missing permission can block queue-to-match creation,
member movement, private result handling, or cleanup.

## 4. Staff Operating Guide

Use this under pressure:

- Review unresolved matches with `/match review-inbox`.
- Treat suspicious rematch holds as review holds, not proof of abuse.
- Use `/match force-result` only when normal voting is stuck, expired, disputed, or staff-reviewed.
- Use `/match force-close` when a match is invalid, abandoned, broken by setup, or cannot be fairly resolved.
- Use `/match rehost-history` for disputes involving changed room ID, password, or key.
- Use `/admin system-status` for launch health summaries.
- Use `/admin bot-voice-status` for persistent voice details.
- Keep emergency coin adjustment disabled. Enable it only for owner-approved audited correction, then disable it again.

Staff should never:

- Casually add/remove ranked points.
- Casually add/remove coins.
- Bypass result flow without emergency reason.
- Resolve disputes without checking match context, review inbox, and audit/history.

Launch-day ownership:

- Queue/match watcher: watches live queues and official match flow.
- Staff-resolution watcher: watches review inbox, disputes, and force-result/force-close.
- Infrastructure watcher: watches permissions, voice, cleanup, restart, and logs.
- Sign-off owner: makes go/no-go decisions.

## 5. Launch-Day Monitoring Checklist

Observe only:

- Occasional queue timeout.
- Isolated ready-check timeout.
- Normal anti-rematch hold.
- Single user input error.

Investigate immediately:

- Repeated queue creation failures.
- Room-info timeout spike.
- Unresolved match spike.
- Command sync issue.
- Voice reconnect warning.
- Cleanup repair warning.

Stop launch:

- Match creation failures.
- Rank/economy correctness uncertainty.
- Private result leak.
- Repeated member movement failure.
- Cleanup deleting active evidence.
- DB migration/schema failure.

Watch continuously:

- Queue creation failures.
- Match creation failures.
- Room-info timeouts.
- Ready-check timeouts.
- Unresolved match count.
- Anti-rematch hold count.
- Cleanup failures.
- Voice reconnect failures.
- Wallet/reward anomalies.
- Interaction latency logs.

## 6. Log / Diagnostics Review Checklist

Before launch, review:

- Startup health.
- Command sync status.
- Migration/schema health.
- Scheduler summary.
- Cleanup summary.
- Persistent voice status.

During launch, review logs for:

- `interaction_acknowledged`
- `interaction_completed`
- `prefix_command_completed`
- match provisioning failures
- cleanup failures
- recovery failures

Use:

- `/admin system-status` for queues, matches, unresolved counts, backlog, runtime, voice, and schema.
- `/admin bot-voice-status` for persistent voice.
- Logs to confirm slow paths are not concentrated in queue join, ready, room-info submit, vote submit, or force-result.

Stop launch if diagnostics show broken schema, repeated match resource failures, or recovery/cleanup cannot keep active flow safe.

## 7. Launch Rehearsal Checklist

Use:

- Real launch staff/admin roles.
- Real player accounts across both teams.
- Actual launch queue channels.
- Actual result/match categories.
- Actual waiting voice channels.

Run:

- One clean flow: queue, ready-check, room info, official match, votes/MVPs, confirmed result, cleanup, voice return.
- One edge-case flow: host transfer or host disappearance, plus ready-check timeout or room-info timeout.
- One staff drill: disputed/expired/staff-review match resolved through review inbox and force-result or force-close.
- One restart drill during an active queue or result-pending match.
- Full Season 2 regression after any rehearsal fix.

## 8. Go / No-Go Sign-Off Criteria

Go only if:

- Queue flow works end to end and duplicate prevention holds.
- Official match creation creates result channel, team voices, moves members, and announces correctly.
- Result flow stays private.
- Rank changes follow locked fairness rules.
- Wallet rewards are correct and idempotent.
- Restart/recovery is safe enough for active queues and matches.
- Staff tools are usable, staff-gated, and audited.
- Live delay is acceptable on core interactions.
- Full Season 2 regression passes.

No-Go if:

- Any major queue blocker remains.
- Match creation fails repeatedly.
- Rank/economy correctness is uncertain.
- Private result handling leaks.
- Cleanup or voice handling breaks the match flow.
- Staff cannot resolve unresolved matches safely.

## 9. Rollback / Incident Response Checklist

If queue flow fails:

- Pause ranked queue creation.
- Announce the pause to staff.
- Preserve existing queue/match evidence.
- Fix only the blocking path and re-test queue flow.

If rank/economy correctness is uncertain:

- Pause result confirmation.
- Do not force-result except to preserve records.
- Investigate rating history and wallet ledger.
- Resume only after correctness is proven.

If restart/recovery fails:

- Pause new queues.
- Preserve active match evidence.
- Use staff review or force-close only when needed.
- Re-test restart state before resuming.

If cleanup/voice breaks:

- Stop automated launch progression.
- Preserve result evidence.
- Move players manually only when safe.
- Fix permissions/cleanup before continuing.

Limited operation is allowed when:

- Queue and match flow work.
- Rank/economy correctness is safe.
- Only non-core shop/cosmetic surfaces are affected.

Full rollback when:

- DB migration fails.
- Private result handling fails.
- Rank/economy correctness is compromised.
- Match creation repeatedly fails.

## 10. Non-Blocking Polish List

Can wait unless it causes real rehearsal confusion:

- Minor embed wording polish.
- Minor command help copy polish.
- Small staff-guide wording improvements.
- Cosmetic layout tweaks.
- Additional examples or screenshots for staff docs.

## 11. Post-Launch Backlog Separation

Post-launch:

- Tournament expansion.
- Bigger shop systems.
- Extra cosmetics.
- Advanced economy.
- Extra dashboards.
- Database-level duplicate queue enforcement unless app-level protection fails.
- Deeper analytics.
- Richer moderation views.
- Long-term season-history polish.

Launch-only:

- Queue.
- Rank.
- Economy.
- Delay.
- Stability/recovery.
- Staff emergency workflows.
- Deployment safety.
- Monitoring.
- Sign-off.

## 12. Strict Phase 3 Summary

Phase 3 is an operational launch gate. Do not add features. Freeze the bot except for
true launch-blocking fixes. Apply migrations, verify config and Discord permissions,
run the live rehearsal, monitor the right signals, and use the go/no-go criteria. If
rehearsal passes and regression remains green, Highlight Manger is ready for Season 2
launch sign-off.
