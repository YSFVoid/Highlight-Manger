# Highlight Manger

Highlight Manger is the Season 2 production runtime for a competitive Discord server. It manages ranked queues, room-info-before-match conversion, official match lifecycle, rank progression, coins, shop, tournaments, moderation, restart recovery, and persistent bot voice.

## Season 2 Launch Gate

Phase 3 deployment readiness lives in:

- [`deploy/season2-launch-readiness.md`](deploy/season2-launch-readiness.md)

Use that runbook for final migrations, environment verification, Discord permission checks, staff operations, launch monitoring, rehearsal, rollback, and go/no-go sign-off. Feature work should stay frozen during Phase 3 except for true launch-blocking fixes.

## Post-Launch Growth

Phase 4 controlled growth lives in:

- [`deploy/phase4-post-launch-growth.md`](deploy/phase4-post-launch-growth.md)

Use that roadmap after launch to prioritize improvements from real staff/player feedback, diagnostics, support burden, and live usage. Queue, rank, economy, result privacy, and staff trust remain protected while tournaments, shop, diagnostics, and polish grow carefully.

## Stack

- Python 3.11+
- `discord.py`
- PostgreSQL / Supabase Postgres
- SQLAlchemy async
- Pydantic v2
- `structlog`
- `PyNaCl` and `davey` for voice support
- Pillow for card rendering

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
- `/admin set-apostado-match-ping`
- `/admin set-highlight-match-ping`
- `/admin set-esport-match-ping`
- `/admin set-waiting-voice-channels`
- `/admin record-phase4-evidence`
- `/admin phase4-evidence`
- `/admin rename-members`
- `/match review-inbox`
- `/match rehost-history`
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
5. The bot creates result resources, moves waiting players when possible, uses the configured per-ruleset match ping target, and opens result voting.
6. Votes confirm the result, then rank and coins update transactionally.

## Recovery And Stability Notes

- Queue, match, and vote deadlines are DB-driven.
- Button and modal handlers acknowledge early to avoid Discord interaction timeouts.
- Card UI stays enabled; rendering is warmed and cached for production.
- Persistent voice tracks explicit runtime status and retry reason.
- `/admin system-status` surfaces sync state, active queues, active matches, cleanup state, and recovery backlog.

