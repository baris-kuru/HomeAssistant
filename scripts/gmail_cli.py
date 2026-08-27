#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.gmail_service import authorize, get_status, import_client_secret, list_recent_messages


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Gmail helper for HomeAssistant/OpenClaw.")
    sub = parser.add_subparsers(dest="command", required=True)

    import_client = sub.add_parser("import-client", help="Import a Gmail OAuth desktop client JSON file.")
    import_client.add_argument("--source", required=True)

    sub.add_parser("status", help="Show Gmail connector status.")
    sub.add_parser("authorize", help="Run the local OAuth browser flow and store a refresh token.")

    recent = sub.add_parser("recent", help="List recent Gmail messages.")
    recent.add_argument("--max-results", type=int, default=10)
    recent.add_argument("--query", default="in:inbox newer_than:14d")

    args = parser.parse_args()

    try:
        if args.command == "import-client":
            result = import_client_secret(args.source)
        elif args.command == "status":
            result = get_status()
        elif args.command == "authorize":
            result = authorize()
        elif args.command == "recent":
            result = list_recent_messages(max_results=args.max_results, query=args.query)
        else:
            raise ValueError(f"Unknown command: {args.command}")
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
