# OpenCode Parallel Duo Draft

This folder contains a non-destructive draft of a tighter parallel-coding workflow for OpenCode.

Nothing here is live yet.

The goal is to let:
- `orchestrator` act like a manager who splits work, coordinates progress, and asks for approval before dispatch
- `build` act like a structured, decisive finisher who closes ambiguity and delivers coherent implementation slices
- `fullstack` act like an exploratory, analytical engineer who maps unknowns, surfaces tradeoffs, and proposes strong implementation paths

## Design Intent

This workflow is meant to feel closer to:
- a small engineering team with explicit ownership
- two developers working in parallel on disjoint tracks
- one manager coordinating checkpoints and reporting upward

It is not meant to be:
- a swarm of overlapping coders editing the same files
- three agents all rediscovering the same repo context
- uncontrolled parallel work without ownership boundaries

## Proposed Team Behavior

1. `orchestrator` inspects the approved goal and creates a work division.
2. `orchestrator` assigns clear ownership to `build` and `fullstack`.
3. `fullstack` handles the more ambiguous or exploratory slice first.
4. `build` handles the more structured or integration-heavy slice.
5. `orchestrator` tracks progress and decides whether work can proceed in parallel or should be serialized.
6. `orchestrator` reports the execution plan to the user and waits for explicit confirmation before dispatching the workers.
7. `review` and `test` remain downstream gates, not default planning participants.

## Why This Pairing Works

`fullstack` should be strong at:
- exploring incomplete requirements
- identifying multiple viable approaches
- spotting hidden system interactions
- quickly turning broad requests into concrete implementation options

`build` should be strong at:
- making firm structure decisions
- choosing the most durable implementation path
- reducing ambiguity
- integrating multiple moving pieces into a coherent slice

This creates a useful tension:
- `fullstack` expands the solution space
- `build` narrows it into a reliable outcome
- `orchestrator` decides how much exploration is necessary and when to lock the path

## Draft Files

- `orchestrator-manager.draft.md`
- `build-strategist.draft.md`
- `fullstack-explorer.draft.md`
- `apply-later.md`

## Safe Rollout Plan

After the current OpenCode run is complete:
1. review these draft prompts
2. confirm the team behavior feels right
3. apply the prompt changes to the live OpenCode config and agents
4. test on one bounded feature before using it for a larger project slice
