# Fireworks Secret Handling Note

Date: 2026-04-18

We tested a safer Fireworks secret setup and then intentionally reverted the project back to a simpler `.env`-based flow for now.

## Safer Setup We Configured

- keep `FIREWORKS_API_KEY` outside the repo
- load it from shell environment or macOS Keychain at launch
- keep `.env.example` as a placeholder only
- point OpenCode provider config at `FIREWORKS_API_KEY` instead of hardcoding the key

## Why We Reverted

- current spend/credit level is small
- simplest local workflow matters more right now
- the app should start without relying on shell/keychain setup every time

## Current State

- HomeAssistant project uses `FIREWORKS_API_KEY` directly in `.env`
- launcher is back to the simpler repo-based startup flow
- `.env.example` still documents the safer placeholder approach
- OpenCode secret handling was left on the environment-based path

## Important Caveat

Putting the Fireworks key in the project `.env` is convenient, but agents with repo read access can potentially see it.

## If We Want To Restore The Safer Setup Later

1. remove `FIREWORKS_API_KEY` from the project `.env`
2. load it from shell or Keychain
3. restore launcher-side secret loading
4. keep provider configs reading from `FIREWORKS_API_KEY`
