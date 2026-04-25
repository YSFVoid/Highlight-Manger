# Phase 4 Live Evidence Log

Use this log after Season 2 launch to decide Phase 4 work from real evidence.
Do not turn guesses, one-off complaints, or nice-to-have ideas into roadmap
items until they are tied to live player friction, staff burden, diagnostics,
logs, support volume, or trust risk.

Admins can record and review live evidence in Discord:

- `/admin record-phase4-evidence`
- `/admin phase4-evidence`

## Evidence Sources

Collect from:

- Staff notes from review inbox, force-result, force-close, diagnostics, rehost history, shop, and tournament operation.
- Player feedback from queue, room info, voting, wallet, shop, and ranked clarity.
- Bot diagnostics for queues, matches, unresolved counts, cleanup, recovery, voice, schema, and backlog.
- Logs for interaction delay, match provisioning, cleanup failures, voice movement, reward anomalies, and command errors.
- Support burden from repeated questions, tickets, manual staff actions, or unresolved match handling.

## Daily Capture Template

Copy one block per issue.

```text
Date:
Reported by:
Source:
Area: Queue / Rank / Economy / Staff Ops / Monitoring / Shop / Tournament / UX
Summary:
Evidence:
Frequency: One-off / Repeated / Widespread
Impact: Low / Medium / High / Critical
Trust risk: None / Low / Medium / High
Staff burden: None / Low / Medium / High
Player friction: None / Low / Medium / High
Recommended action: Observe / Fix soon / Phase 4 candidate / Defer
Owner:
Status: New / Reviewing / Accepted / Deferred / Done
Notes:
```

## Triage Rules

Must fix soon:

- Repeated player confusion in queue, room info, voting, wallet, or shop.
- Staff repeatedly needing manual work to resolve the same situation.
- Diagnostics or logs showing recurring cleanup, voice, reward, or interaction-delay problems.
- Any issue that threatens rank trust, economy trust, result privacy, or staff auditability.

Phase 4 candidate:

- Tournament check-in or seeding friction with repeated staff evidence.
- Shop/catalog improvements that reduce fulfillment burden.
- Admin or UX polish that repeatedly saves staff time or reduces player confusion.
- Monitoring improvements that make incidents easier to understand.

Defer:

- One-off complaints without supporting evidence.
- Cosmetic work that does not improve clarity, speed, staff usability, or trust.
- Large tournament, economy, or dashboard expansion before usage proves demand.
- Anything that reopens locked launch rules without clear live evidence.

## Weekly Review Checklist

Review once per week during early Phase 4:

- Top three player pain points.
- Top three staff pain points.
- Most common unresolved match reason.
- Queue timeout and ready-check timeout pattern.
- Room-info timeout pattern.
- Anti-rematch hold pattern.
- Shop support burden.
- Cleanup or voice reliability incidents.
- Slowest visible interaction path.
- Any protected system that should stay frozen.

## Decision Output

At the end of each review, record:

```text
Week:
Accepted Phase 4 work:
Rejected or deferred work:
Evidence behind each accepted item:
Systems that remain frozen:
Next review date:
```

Only accepted work with clear evidence should move into implementation planning.
Use [`phase4-first-task-selection.md`](phase4-first-task-selection.md) to score
accepted candidates and choose the first implementation item.
