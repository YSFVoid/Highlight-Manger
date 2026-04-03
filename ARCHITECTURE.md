# Highlight Manger Architecture

## Canonical Runtime

The Season 2 production runtime is:

1. `app.py`
2. `src/highlight_manager/app/`
3. `src/highlight_manager/db/`
4. `src/highlight_manager/modules/`
5. `src/highlight_manager/tasks/`
6. `src/highlight_manager/ui/`

Operationally, the supported startup contract is:

```bash
python app.py
```

## Runtime Responsibilities

- `app/`: Discord bot entrypoint, config, runtime wiring, command registration
- `db/`: SQLAlchemy models, session factory, migrations
- `modules/`: business logic grouped by domain
- `tasks/`: recovery, cleanup, deadline polling
- `ui/`: card rendering, embeds, shared theme

## Authoritative State Machines

- Queue state and rules live in:
  - `src/highlight_manager/modules/common/enums.py`
  - `src/highlight_manager/modules/matches/states.py`
  - `src/highlight_manager/modules/matches/service.py`
- Match state and result rules live in:
  - `src/highlight_manager/modules/common/enums.py`
  - `src/highlight_manager/modules/matches/service.py`

## Legacy Runtime Trees

These paths are legacy and are not the production source of truth:

- `src/highlight_manager/commands/`
- `src/highlight_manager/services/`
- `src/highlight_manager/repositories/`
- `src/highlight_manager/models/`
- `src/highlight_manager/interactions/`
- `src/highlight_manager/jobs/`
- `src/highlight_manager/utils/`

They remain in the repository for reference during cleanup, but imports from those packages are tracked at runtime so accidental usage can be surfaced in logs and `/admin system-status`.

Additional top-level directories such as `src/commands/`, `src/services/`, `src/models/`, `src/repositories/`, `src/interactions/`, `src/jobs/`, and `src/utils/` are also legacy leftovers and are not used by the Season 2 runtime.
