# OpenCode Agentic Architecture Summary

## Purpose

This document captures the architecture decisions, workflow design, model routing, and reasoning evolution from the OpenCode setup work for this project.

The goal was not just to configure agents, but to build an experimental, practical, and budget-aware agentic coding environment that supports:

- strong product and architecture thinking
- useful specialization across agents
- robust implementation and verification
- lower cost than an "everyone talks every time" swarm
- a learning-oriented workflow that helps the operator think more like a senior engineer

## Project Direction

The product direction evolved toward a product called `Persona`.

The current strategic direction is:

- cloud-only
- no local model usage in the product direction
- more agentic OpenClaw architecture with multiple agents for different task classes
- single-user first
- multi-user kept in mind in the architecture, but deferred as an implementation constraint for phase 1
- security and concurrency are not ignored, but they should not block the first meaningful product slice

## Key Operational Findings

### 1. OpenCode startup was slower than expected

The main cause was not just model latency.

Important discoveries:

- OpenCode was at times starting from `/Users/bariskuru` instead of the project root.
- That caused file watching, globbing, and snapshotting over the whole home directory.
- A stale snapshot `index.lock` in OpenCode's local snapshot cache also contributed to long delays.

Practical conclusion:

- OpenCode should be launched from the project root:

```bash
cd /Users/bariskuru/Projects/HomeAssistant && opencode .
```

### 2. Local model confusion was caused by a separate background service

OpenCode was reconfigured to use Fireworks/OpenRouter rather than local `llama.cpp`.

However, a local `llama-swap` service was still running through a macOS LaunchAgent for the Home Assistant stack. That explained why the machine still behaved as if local inference was active.

Practical conclusion:

- OpenCode and HomeBot/OpenClaw model routing are distinct concerns
- local model infra can still exist for the app stack even after OpenCode stops using it

### 3. Skills were not the cause of startup slowness

OpenCode initially showed `skill count=0`.

That was not itself a performance problem. Skills are optional and loaded on demand.

To make project-local context more reusable, several project skills were added under `.opencode/skills/`.

## Fireworks and Homebrew Findings

### Fireworks quota result

Using `firectl`, the Fireworks account quota was checked.

Notable values:

- `serverless-inference-rpm`: `6000`
- `monthly-spend-usd`: `50`

Interpretation:

- account-level request ceiling is healthy
- real bottlenecks for agentic coding are more likely to be token throughput, large prompt sizes, and long-context latency
- practical default parallelism should stay modest

Recommended default parallelism:

- best default: `2` simultaneous active worker tracks
- usually okay: `3`
- more than that only for clearly independent, lightweight work

### Homebrew/firectl path

Homebrew was outdated and could not handle the current macOS version.

Fix path:

- install fresh supported Homebrew in `/opt/homebrew`
- install `firectl`
- sign in and use `firectl quota list`

## Model Routing Evolution

Several model-routing iterations happened before the final split.

### Earlier thinking

Earlier iterations experimented with:

- local `llama.cpp`
- Fireworks `GLM-5.1`
- Fireworks `Kimi K2.5`
- a smaller number of OpenRouter fallbacks

### Final model split

The final chosen setup is:

- `orchestrator`: `Qwen 3.6 Plus`
- `fullstack`: `Qwen 3.6 Plus`
- `ux`: `Kimi 2.5`
- `architect`: `Qwen 3.6 Plus`
- `review`: `GLM-5.1`
- `test`: `MiniMax 2.7`
- `debug`: `Qwen 3.6 Plus`

Additional system-level routing:

- `meeting`: `Qwen 3.6 Plus`
- `compaction`: `Qwen 3.6 Plus`
- `title`: `Qwen 3.6 Plus`

### Why this split

Reasoning behind the final split:

- `Qwen 3.6 Plus` became the main workhorse because it offers strong general capability and large context
- `Kimi 2.5` was retained for `ux` because model diversity is useful in product/experience discussions
- `GLM-5.1` was reserved for `review` to provide a differently trained high-standards checker
- `MiniMax 2.7` was selected for `test` as a cheaper verifier

### Context window decisions

`Qwen 3.6 Plus` was updated to reflect a much larger context window than the initial placeholder configuration.

Configured value:

- `context`: `1000000`
- `output`: `65536`

HomeBot/OpenClaw was also updated to use the larger context budget for `Qwen 3.6 Plus`.

## Agent Roster Evolution

### Initial direction

The setup first grew toward a larger specialist team:

- architect
- build
- backend
- frontend
- debug
- review
- docs
- orchestrator

### Simplification

The design then intentionally moved away from too many overlapping agents.

Important simplifications:

- `backend` and `frontend` were merged into `fullstack`
- `review` and `docs` were removed from meetings by default
- `debug` and `test` were also removed from meetings by default unless explicitly requested
- a dedicated `ux` specialist was added for product and experience thinking

### Final specialist roles

- `orchestrator`: manager and coordinator
- `fullstack`: implementation
- `architect`: planning and system design
- `ux`: product/interaction/mental-model design
- `debug`: root cause analysis
- `test`: targeted verification and regression thinking
- `review`: strong independent audit/checker
- `docs`: notes, documentation, durable written artifacts
- `meeting`: facilitator for multi-agent opinion synthesis

## Permission and Tool Access Model

The agent differences are driven mostly by permissions.

### Read-only coordinator/thinking agents

These are primarily analysis/coordination agents:

- `orchestrator`
- `meeting`
- `architect`
- `ux`
- `review`

Typical characteristics:

- `edit`: denied
- limited or tightly constrained `bash`
- `webfetch`: allowed

### Full shell but read-only specialists

These can inspect and test broadly, but do not edit:

- `debug`
- `test`

Typical characteristics:

- `edit`: denied
- `bash`: broadly allowed
- `webfetch`: allowed

### Editing agents

These are allowed to change files:

- `fullstack`
- `docs`

Typical characteristics:

- `edit`: allowed
- `fullstack` has broad shell access
- `docs` has limited shell access

### Task delegation

Built-in task permission is explicitly enabled for:

- `build`
- `orchestrator`
- `meeting`

This is what allows them to invoke other agents as subtasks.

## Workflow Evolution

### Early workflow design

The system first evolved around specialized agents plus direct commands for:

- planning
- debugging
- review

### Expanded workflow routes

Structured workflow commands were then added:

- `/feature`
- `/bugfix`
- `/refactor`
- `/security`
- `/test`
- `/project`

### Project-from-scratch workflow

`/project` became the dedicated greenfield workflow.

Purpose:

- turn a product direction into a phased implementation plan
- use architect + implementation + testing + review in sequence
- stop for approval before execution if asked

### Meeting workflows

Two kinds of meetings were added.

#### `/meeting`

Designed for:

- stronger synthesis
- two-round expert discussion
- shared notes
- round-2 revisions after seeing others' positions

This is better for:

- deep strategy decisions
- architecture debates
- product direction refinement

#### `/smeeting`

Designed for:

- lower-cost, faster decision support
- one round only
- small specialist set
- final orchestrator-style recommendation

Default intended participant set:

- `architect`
- `fullstack`
- `ux`

This is better for:

- quick direction calls
- updating a strategic position after the user adds a strong opinion
- deciding the next workflow command

## Meeting Design Evolution

The meeting design changed significantly through experimentation.

### First idea

The original idea was closer to a swarm or a "conference room" where multiple agents would all get involved.

### Realistic constraint

The more practical model in OpenCode is:

- a facilitator asks named agents for opinions
- child sessions are used for each participant
- results are synthesized centrally

This is not a literal live shared group chat among agents, but it is close enough for a structured meeting workflow.

### Two-round meeting

The normal meeting flow was upgraded to:

1. round 1 opinions
2. shared notes
3. round 2 revised positions
4. synthesis

### Small meeting

Because two rounds can be too expensive or slow for many cases, `/smeeting` was added:

- one round only
- user's opinion treated as a key input
- final orchestrator-style recommendation

This became the preferred lightweight strategy tool.

## Persona Product Thinking Evolution

The strategic product thinking evolved in several steps:

1. start from a Home Assistant-style AI project
2. consider a broader white-collar assistant direction
3. use agent meetings to explore what would make the product indispensable
4. rename the product to `Persona`
5. shift toward:
   - cloud-only execution
   - multi-agent OpenClaw architecture
   - single-user-first product wedge

The final approach is intentionally experimental:

- use agentic workflows not just for implementation, but for learning and product reasoning
- use specialized agent opinions to teach better engineering judgment
- keep enough diversity to challenge assumptions, but not so much that token usage explodes

## Cost Optimization Thinking

One of the important design goals was to make the system robust without turning every task into a premium multi-agent committee.

Key conclusions:

- stable project direction should live in reusable files/skills, not be repasted constantly
- not every task needs every agent
- diversity is valuable at decision gates, not on every turn
- review and testing should be invoked intentionally
- meetings should stay small by default
- practical parallelism should remain modest

The preferred operational pattern became:

- cheap, strong default execution core
- selectively invoked specialist opinions
- premium or differently trained review only when the leverage is high

## Current Recommended Operating Pattern

### Direction work

Use:

- `/smeeting` for quick directional decisions
- `/meeting` for deeper synthesis

Default participants:

- `architect`
- `fullstack`
- `ux`

### Greenfield planning

Use:

- `/project`

This should:

- read the latest notes
- convert strategy into a phased plan
- assign responsibilities
- stop for approval if asked

### Implementation

Use:

- `fullstack` for real coding
- `orchestrator` for management and coordination

### Verification

Add:

- `test` for regression/risk checking
- `review` for critical audit

Only when actually useful.

### Debugging

Use:

- `debug`

Only when there is a real failure or uncertainty about root cause.

## Final Summary

The system evolved from a broad, somewhat swarm-like ambition into a more disciplined agentic architecture:

- smaller default teams
- deliberate role separation
- cloud-first model strategy
- large-context strong primary models
- selective diversity for stronger judgment
- lightweight and heavyweight meeting modes
- manager-style orchestration instead of chaotic autonomy

The result is an experimental but practical OpenCode operating model that balances:

- robustness
- cost
- speed
- learning value
- product thinking

For the current project direction, the next major work should center on `Persona` as a cloud-only, agentic, single-user-first product with multi-user-aware architecture and a strong first vertical slice.
