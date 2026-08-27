"""Evaluate the LLM router against a labeled test set.

Usage:
    python -m backend.services.router_eval
    python -m backend.services.router_eval --model accounts/fireworks/models/gpt-oss-120b
    python -m backend.services.router_eval --compare accounts/fireworks/models/gpt-oss-120b
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from ..schemas import RouteResponse
from .fireworks_service import chat_structured
from .router import LLM_ROUTE_PROMPT, ROUTER_MODEL

EVAL_FILE = Path(__file__).with_name("router_eval.json")


async def classify(text: str, model: str) -> RouteResponse | None:
    try:
        return await chat_structured(
            messages=[{"role": "user", "content": text}],
            schema=RouteResponse,
            system=LLM_ROUTE_PROMPT,
            model=model,
            max_tokens=150,
            temperature=0.1,
        )
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return None


async def run_model(model: str, cases: list[dict]) -> tuple[int, int, list[dict]]:
    correct_lane = 0
    correct_domain = 0
    misses: list[dict] = []
    tasks = [classify(c["text"], model) for c in cases]
    results = await asyncio.gather(*tasks)
    for case, result in zip(cases, results):
        if result is None:
            misses.append({**case, "got_lane": None, "got_domain": None})
            continue
        lane_ok = result.lane == case["lane"]
        domain_ok = result.domain == case["domain"]
        if lane_ok:
            correct_lane += 1
        if domain_ok:
            correct_domain += 1
        if not (lane_ok and domain_ok):
            misses.append({
                **case,
                "got_lane": result.lane,
                "got_domain": result.domain,
                "reason": result.reason,
            })
    return correct_lane, correct_domain, misses


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=ROUTER_MODEL, help="Model to evaluate")
    parser.add_argument("--compare", help="Second model to evaluate side-by-side")
    args = parser.parse_args()

    cases = json.loads(EVAL_FILE.read_text())
    total = len(cases)
    print(f"Loaded {total} cases from {EVAL_FILE.name}\n")

    models = [args.model] + ([args.compare] if args.compare else [])
    for model in models:
        print(f"=== {model} ===")
        lane_ok, domain_ok, misses = await run_model(model, cases)
        print(f"  Lane accuracy:   {lane_ok}/{total} ({100*lane_ok/total:.0f}%)")
        print(f"  Domain accuracy: {domain_ok}/{total} ({100*domain_ok/total:.0f}%)")
        if misses:
            print(f"  Misses ({len(misses)}):")
            for m in misses:
                print(
                    f"    [{m.get('got_lane')}/{m.get('got_domain')}] "
                    f"expected [{m['lane']}/{m['domain']}]  {m['text']!r}"
                )
        print()


if __name__ == "__main__":
    asyncio.run(main())
