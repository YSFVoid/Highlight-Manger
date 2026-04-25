# Phase 4 First Task Selection

Use this review to choose the first Phase 4 implementation item from live
evidence. This file is intentionally strict: Phase 4 work should start from
trust risk, repeated friction, staff burden, or operational evidence, not from
ideas that only sound interesting.

## 1. Required Inputs

Before selecting work, gather:

- At least three live evidence entries from `phase4-live-evidence-log.md`, or
- One critical trust, privacy, rank, reward, cleanup, or staff-operation incident.

If neither condition is true, continue observing instead of implementing.

## 2. Evidence Categories

Score each candidate from `0` to `3` in every category.

| Category | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| Trust risk | None | Low confusion | Moderate trust concern | Rank, reward, privacy, or staff-power risk |
| Frequency | One-off | Repeated once | Repeated several times | Widespread or daily |
| Staff burden | None | Minor explanation | Repeated manual work | Blocks staff operations |
| Player friction | None | Minor confusion | Repeated user failure | Blocks match/shop flow |
| Operational risk | None | Cosmetic/log noise | Recoverable incident | Cleanup, voice, DB, or match-flow risk |
| Scope safety | Risky rewrite | Touches core flow broadly | Small contained change | Safe, narrow, reversible |

Priority score:

```text
trust risk + frequency + staff burden + player friction + operational risk + scope safety
```

## 3. First Task Gate

The first Phase 4 task must pass all gates:

- Evidence-backed by repeated entries or one high-severity incident.
- Does not redesign the official match flow.
- Does not loosen emergency-only staff power.
- Does not casually change rank or coin rules.
- Can be shipped as a narrow V1.
- Has a clear success signal after release.

If two candidates tie, choose the one that reduces staff burden or protects
rank/economy/result trust.

## 4. Candidate Review Table

Use one row per candidate.

| Candidate | Evidence refs | Trust | Frequency | Staff | Player | Ops | Scope | Total | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
|  |  |  |  |  |  |  |  |  |  |

Decision values:

- `Start now`
- `Plan next`
- `Observe`
- `Defer`

## 5. Recommended Default Order

When evidence is comparable, prefer:

1. Rank, reward, result privacy, or staff-power trust risks.
2. Queue or match-flow friction that repeatedly blocks players.
3. Staff review, diagnostics, or audit friction that slows resolution.
4. Wallet/shop confusion or fulfillment burden.
5. Tournament check-in or seeding friction when real tournament operations prove demand.
6. Cosmetic or convenience polish.

## 6. Decision Record

Record the chosen item before implementation:

```text
Chosen Phase 4 task:
Date chosen:
Evidence refs:
Why this first:
Systems protected:
Out of scope:
Success signal:
Rollback/safety note:
```

Implementation should not begin until this record is filled from live evidence.
