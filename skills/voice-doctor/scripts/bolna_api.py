#!/usr/bin/env python3
"""Read-only Bolna API helper for voice-doctor.

  bolna_api.py agents                         list agents (id, name)
  bolna_api.py agent AGENT_ID                 one agent's full config
  bolna_api.py executions AGENT_ID [--days 7] [--max 100] [--status completed]
  bolna_api.py execution EXECUTION_ID         one call, with transcript and latency_data
  bolna_api.py export DIR                     every agent's full config, one JSON file each

Prints JSON to stdout; redirect it to a file. Only GET requests: nothing here can
change an agent or place a call.

The API key comes from BOLNA_API_KEY, or a BOLNA_API_KEY=... line in ./.env.
The key is never printed. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ.get("BOLNA_BASE_URL", "https://api.bolna.ai")
PAGE_SIZE = 50  # API maximum
WINDOW_DAYS = 7  # API rejects from/to ranges longer than this


def api_key() -> str:
    key = os.environ.get("BOLNA_API_KEY")
    if not key and os.path.isfile(".env"):
        with open(".env", encoding="utf-8") as fh:
            for line in fh:
                name, _, value = line.strip().partition("=")
                if name.strip() == "BOLNA_API_KEY":
                    key = value.strip().strip("\"'")
    if not key:
        sys.exit("BOLNA_API_KEY is not set. Create a key at platform.bolna.ai -> Developers -> API Keys, "
                 "then export BOLNA_API_KEY=... or put it in .env.")
    return key


def get(path: str, params: dict | None = None):
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {api_key()}",
        "Accept": "application/json",
        "User-Agent": "voice-doctor/0.1",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        hint = {401: "key rejected", 403: "key rejected or no access to this resource",
                404: "not found: check the id", 429: "rate limited: wait a minute and retry"}.get(e.code, "")
        sys.exit(f"Bolna API {e.code} on {path}{' (' + hint + ')' if hint else ''}: {body}")
    except urllib.error.URLError as e:
        sys.exit(f"Could not reach {BASE_URL}: {e.reason}")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def executions(agent_id: str, days: int, limit: int, status: str | None) -> list:
    """Newest first, walking back in 7-day windows until `limit` calls or `days` covered."""
    out: list = []
    end = datetime.now(timezone.utc)
    start_bound = end - timedelta(days=days)
    while end > start_bound and len(out) < limit:
        start = max(start_bound, end - timedelta(days=WINDOW_DAYS))
        page = 1
        while len(out) < limit:
            data = get(f"/v2/agent/{agent_id}/executions", {
                "from": iso(start), "to": iso(end), "page_number": page,
                "page_size": PAGE_SIZE, "status": status,
            })
            rows = data.get("data", []) if isinstance(data, dict) else data
            out.extend(rows)
            if not (isinstance(data, dict) and data.get("has_more")) or not rows:
                break
            page += 1
        end = start
    return out[:limit]


def list_agents() -> list:
    data = get("/v2/agent/all")
    rows = data if isinstance(data, list) else data.get("data", [])
    return [r for r in rows if isinstance(r, dict)]


def export(directory: str) -> list:
    """Write each agent's full config to DIR/<name>-<id8>.json, for a fleet audit."""
    os.makedirs(directory, exist_ok=True)
    written = []
    for row in list_agents():
        agent_id = row.get("id") or row.get("agent_id")
        if not agent_id:
            continue
        full = get(f"/v2/agent/{agent_id}")
        name = str(full.get("agent_name") or row.get("agent_name") or "agent")
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "agent"
        path = os.path.join(directory, f"{slug}-{str(agent_id)[:8]}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(full, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        written.append(path)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("agents")
    a = sub.add_parser("agent")
    a.add_argument("agent_id")
    e = sub.add_parser("executions")
    e.add_argument("agent_id")
    e.add_argument("--days", type=int, default=7)
    e.add_argument("--max", type=int, default=100)
    e.add_argument("--status", help="e.g. completed")
    x = sub.add_parser("execution")
    x.add_argument("execution_id")
    d = sub.add_parser("export")
    d.add_argument("dir")
    args = ap.parse_args()

    if args.cmd == "agents":
        result = [{"id": r.get("id") or r.get("agent_id"), "name": r.get("agent_name")} for r in list_agents()]
    elif args.cmd == "export":
        written = export(args.dir)
        result = {"exported": len(written), "files": written,
                  "next": f"python3 audit_config.py {args.dir}"}
    elif args.cmd == "agent":
        result = get(f"/v2/agent/{args.agent_id}")
    elif args.cmd == "executions":
        result = {"agent_id": args.agent_id, "data": executions(args.agent_id, args.days, args.max, args.status)}
    else:
        result = get(f"/executions/{args.execution_id}")

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
