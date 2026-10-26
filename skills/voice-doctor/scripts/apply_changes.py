#!/usr/bin/env python3
"""Merge a voice-doctor change file into a Bolna agent and re-score it.

Writes the merged agent to a file (nothing is sent to Bolna), lists every
changed field with its old and new value, says which fields Bolna's PATCH can
change and which need a full PUT, and prints the config and speakability
scores before and after.

Usage:
  apply_changes.py agent.json config-changes.json [-o agent.fixed.json] [--json]

The change file uses the agent's own structure: either the create/PUT shape
({"agent_config": {...}, "agent_prompts": {...}}) or the flat shape that
GET /v2/agent returns. Either works with either agent shape. Objects merge
recursively, the "tasks" list merges item by item, other lists are replaced,
and a null value removes the field. Standard library only.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_config import audit  # noqa: E402
from lint_prompt import detect_platform, extract_agent_text, lint  # noqa: E402

# Fields Bolna's PATCH /v2/agent/{id} accepts (references/bolna.md). Everything
# else needs a full PUT, which replaces the whole agent.
PATCH_AGENT_FIELDS = {"agent_name", "agent_welcome_message", "webhook_url", "ingest_source_config",
                      "telephony_provider", "calling_guardrails", "call_summary_enabled"}
_MISSING = object()


def is_wrapped(d: dict) -> bool:
    return isinstance(d, dict) and isinstance(d.get("agent_config"), dict)


def align(changes: dict, agent: dict) -> dict:
    """Reshape the change file to match the agent's shape (wrapped or flat)."""
    if is_wrapped(agent) == is_wrapped(changes):
        return changes
    if is_wrapped(changes):  # agent is flat
        flat = dict(changes.get("agent_config") or {})
        for k, v in changes.items():
            if k != "agent_config":
                flat[k] = v
        return flat
    wrapped = {"agent_config": {k: v for k, v in changes.items() if k != "agent_prompts"}}
    if "agent_prompts" in changes:
        wrapped["agent_prompts"] = changes["agent_prompts"]
    return wrapped


def merge(base, patch, path="", out=None):
    """Recursively merge patch into base in place; record (path, old, new)."""
    out = [] if out is None else out
    for key, new in patch.items():
        p = f"{path}.{key}" if path else key
        old = base.get(key, _MISSING)
        if new is None:
            if old is not _MISSING:
                del base[key]
                out.append((p, old, None))
        elif isinstance(new, dict) and isinstance(old, dict):
            merge(old, new, p, out)
        elif key == "tasks" and isinstance(new, list) and isinstance(old, list):
            for i, item in enumerate(new):
                if i < len(old) and isinstance(item, dict) and isinstance(old[i], dict):
                    merge(old[i], item, f"{p}[{i}]", out)
                elif i < len(old):
                    out.append((f"{p}[{i}]", old[i], item))
                    old[i] = item
                else:
                    out.append((f"{p}[{i}]", None, item))
                    old.append(item)
        elif old != new:
            base[key] = copy.deepcopy(new)
            out.append((p, None if old is _MISSING else old, new))
    return out


def method_for(path: str) -> str:
    parts = path.split(".")
    if parts[0] == "agent_config":
        parts = parts[1:]
    if not parts:
        return "PUT"
    head = parts[0]
    if head == "agent_prompts" or head in PATCH_AGENT_FIELDS:
        return "PATCH"
    if head.startswith("tasks") and ".synthesizer" in path:
        return "PATCH"
    return "PUT"


def scores(agent: dict) -> dict:
    parts = extract_agent_text(agent)
    a = audit(agent, None)
    out = {"config": a.score, "config_findings": sorted(f.rule for f in a.findings)}
    if isinstance(parts["prompt"], str):
        r = lint(parts["prompt"], parts["welcome"], None, parts["tts"], parts["multilingual"], parts["platform"])
        out.update(speakability=r.score, speakability_findings=sorted(f.rule for f in r.findings))
    return out


def short(v, n=70) -> str:
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def apply(agent: dict, changes: dict):
    merged = copy.deepcopy(agent)
    changed = merge(merged, align(changes, agent) if detect_platform(agent) == "bolna" else changes)
    bolna = detect_platform(agent) == "bolna"  # Vapi and Retell update everything through PATCH
    return merged, [{"field": p, "old": o, "new": n, "method": method_for(p) if bolna else "PATCH"}
                    for p, o, n in changed]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent_json")
    ap.add_argument("changes_json")
    ap.add_argument("-o", "--out", help="where to write the merged agent (default: <agent>.fixed.json)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with open(args.agent_json, encoding="utf-8") as fh:
        agent = json.load(fh)
    with open(args.changes_json, encoding="utf-8") as fh:
        changes = json.load(fh)
    merged, changed = apply(agent, changes)
    out = args.out or os.path.splitext(args.agent_json)[0] + ".fixed.json"
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    before, after = scores(agent), scores(merged)
    result = {"output": out, "changes": changed, "before": before, "after": after,
              "needs_put": any(c["method"] == "PUT" for c in changed),
              "fixed": sorted(set(before["config_findings"]) - set(after["config_findings"])
                              | set(before.get("speakability_findings", [])) - set(after.get("speakability_findings", []))),
              "new_findings": sorted(set(after["config_findings"]) - set(before["config_findings"])
                                     | set(after.get("speakability_findings", [])) - set(before.get("speakability_findings", [])))}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"Wrote {out} ({len(changed)} fields changed). Nothing was sent to Bolna.")
    print(f"Config score: {before['config']} -> {after['config']}")
    if "speakability" in before:
        print(f"Speakability: {before['speakability']} -> {after.get('speakability')}")
    print()
    for c in changed:
        old_s = "(unset)" if c["old"] is None else short(c["old"])
        new_s = "(removed)" if c["new"] is None else short(c["new"])
        print(f"[{c['method']:5}] {c['field']}: {old_s} -> {new_s}")
    print()
    if result["needs_put"]:
        print("Some changes need a full PUT, which replaces the whole agent: back up the current config first.")
    else:
        print("Every change can go through PATCH.")
    if result["new_findings"]:
        print("New findings introduced by the changes: " + ", ".join(result["new_findings"]))
    left = [r for r in after["config_findings"]] + after.get("speakability_findings", [])
    if left:
        print("Still flagged: " + ", ".join(sorted(set(left))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
