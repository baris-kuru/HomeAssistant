---
name: targeted-verification
description: Choose the smallest useful verification steps for this repo instead of broad expensive checks
compatibility: opencode
---

## What I do

- Favor focused verification over large, slow test runs
- Match the check to the changed area
- Encourage short command sequences and clear pass/fail summaries

## Verification approach

- For backend route or agent changes: run the smallest command that reproduces or validates the behavior
- For frontend changes: verify the touched files, the affected flow, and likely regressions
- If no automated tests exist, describe the exact manual verification steps
- If a bug is unclear, reproduce first before proposing broad changes

## When to use me

Use this after edits, during bugfixes, and before calling a task done.
