# Apply Later

This draft is intentionally not live yet.

## Intended Live Changes After Approval

1. Update the live `orchestrator` prompt so it owns work division and coordination by default.
2. Introduce the new `build` prompt characteristics into the live OpenCode setup.
3. Update the live `fullstack` prompt to become the exploratory counterpart.
4. Leave `architect` available, but no longer make it the default decomposer for ordinary execution planning.
5. Keep `review` and `test` as downstream gates rather than default participants in planning.

## Operational Model

Recommended default:
- `orchestrator` plans and dispatches
- `fullstack` explores the ambiguous track
- `build` executes the more structured or integration-heavy track

Recommended limits:
- two active coding workers by default
- add more only for clearly disjoint work
- integrate one completed slice at a time

## Suggested First Trial

Use one medium-sized feature with:
- one ambiguous slice for `fullstack`
- one structured slice for `build`
- one clear integration point

Good examples:
- backend flow plus frontend UI for the same feature
- task routing plus persistence cleanup
- agent workflow update plus user-facing command surface

Avoid first trying this on:
- repo-wide refactors
- highly coupled architecture changes
- large schema rewrites touching many shared files
