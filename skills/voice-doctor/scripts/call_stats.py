#!/usr/bin/env python3
"""Aggregate Bolna call executions into a ranked list of problems.

Reads executions (from bolna_api.py executions, the MCP list_agent_executions
tool, or a dashboard export) and reports, across all calls:
  - outcomes: answer rate, voicemail, who hung up, cost per answered minute
  - latency from latency_data: p50/p95 per component vs Bolna's thresholds
  - turn-taking from interruption_stats: who interrupts whom, longest monologue
  - transcript signals: words per agent turn, "hello? are you there?" moments,
    repeated agent lines, unspeakable text the agent actually said, calls that
    end at the max-duration cap

Usage:
  call_stats.py executions.json [--agent-json agent.json] [--json]

Pass --agent-json to check calls against the agent's call_terminate and voice
engine. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_prompt import (CODE, DEVANAGARI, EMAIL, EMOJI, ISO_DATE, MD_BULLET, MD_INLINE, ROMAN_HINDI,  # noqa: E402
                         URL, find_key, tts_from_synthesizer, words)

# Bolna's documented "slow" thresholds (concepts/call-latencies).
SLOW = {"transcriber": 100, "llm": 1000, "synthesizer": 500}
DEAD_AIR = re.compile(
    r"^\W*(?:hello\W*){1,3}$|are you there|can you hear|hello\?|haan\?|kya\?|suniye|sunai nahi|awaaz nahi|"
    r"हेलो|हैलो|सुनाई नहीं|ಹಲೋ|ಕೇಳಿಸ್ತಿಲ್ಲ", re.I)


def pct(values, p):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = max(0, min(len(vals) - 1, int(round(p / 100 * len(vals) + 0.5)) - 1))
    return vals[k]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_transcript(text: str):
    turns = []
    for raw in (text or "").splitlines():
        m = re.match(r"\s*(assistant|agent|bot|user|customer|human)\s*:\s*(.*)", raw, re.I)
        if m:
            role = "agent" if m.group(1).lower() in ("assistant", "agent", "bot") else "user"
            turns.append([role, m.group(2).strip()])
        elif turns and raw.strip():
            turns[-1][1] += " " + raw.strip()
    return turns


def load_executions(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            return data["data"]
        if "transcript" in data or "latency_data" in data:
            return [data]
    return []


def turn_values(component: dict, key: str, skip_welcome=True):
    out = []
    for t in (component or {}).get("turns", []) or []:
        if skip_welcome and t.get("turn") == -1:
            continue
        out.append(num(t.get(key)))
    return out


def analyse(execs: list, agent: dict | None) -> dict:
    tc = (find_key(agent, ("task_config",)) or {}) if agent else {}
    call_cap = num(tc.get("call_terminate"))
    tts = tts_from_synthesizer(find_key(agent, ("synthesizer",))) if agent else None

    calls, issues_per_call = [], Counter()
    lat = {"ttfa": [], "transcriber": [], "llm": [], "synthesizer": [], "welcome_tts": []}
    inter = {"user_interrupted_agent": [], "agent_interrupted_user": [], "monologue_ms": [], "talk_listen": []}
    agent_turn_words, dead_air_calls, dead_air_lines = [], 0, 0
    repeats, leaks, roman_calls = [], Counter(), 0
    applied = {}
    inconsistent = []

    for e in execs:
        cid = e.get("id") or e.get("execution_id") or f"call-{len(calls) + 1}"
        tel = e.get("telephony_data") or {}
        dur = num(e.get("conversation_duration"))
        if dur is None:
            dur = num(tel.get("duration"))
        turns_pre = parse_transcript(e.get("transcript", ""))
        # Dry-run transcripts have no duration; a transcript with a caller in it counts as answered.
        answered = bool(dur and dur > 0) or (dur is None and any(r == "user" for r, _ in turns_pre))
        vm = bool(e.get("answered_by_voice_mail"))
        turns = parse_transcript(e.get("transcript", ""))
        agent_lines = [t for r, t in turns if r == "agent"]
        user_lines = [t for r, t in turns if r == "user"]
        calls.append({"id": cid, "answered": answered, "voicemail": vm, "duration": dur,
                      "hangup_by": tel.get("hangup_by"), "hangup_reason": tel.get("hangup_reason"),
                      "cost": num(e.get("total_cost")), "agent_words": sum(len(words(t)) for t in agent_lines)})

        if not applied:
            ub = e.get("usage_breakdown") or {}
            for k in ("endpointing", "incremental_delay", "buffer_size", "hangup_after_silence"):
                v = find_key(ub, (k,))
                if v is not None:
                    applied[k] = v
            if tts is None:
                synth = find_key(ub, ("synthesizer",))
                if isinstance(synth, dict):
                    tts = tts_from_synthesizer({"provider": synth.get("provider"),
                                                "provider_config": {"model": synth.get("model")}})

        ld = e.get("latency_data") or {}
        if ld:
            lat["ttfa"].append(num(ld.get("time_to_first_audio")))
            for t in (ld.get("transcriber") or {}).get("turns", []) or []:
                lat["transcriber"] += [num(s.get("audio_to_text_latency")) for s in t.get("turn_latency", []) or []]
            lat["llm"] += turn_values(ld.get("llm"), "time_to_first_token")
            lat["synthesizer"] += turn_values(ld.get("synthesizer"), "time_to_first_token")
            lat["welcome_tts"] += [num(t.get("time_to_first_token")) for t in
                                   (ld.get("synthesizer") or {}).get("turns", []) or [] if t.get("turn") == -1]
            st = ld.get("interruption_stats") or {}
            spoken = (num(st.get("user_speaking_ms")) or 0) + (num(st.get("agent_speaking_ms")) or 0)
            if st and dur and spoken > dur * 1000 * 1.2:
                inconsistent.append(cid)
            if st:
                inter["user_interrupted_agent"].append(num(st.get("user_interrupted_agent_count")))
                inter["agent_interrupted_user"].append(num(st.get("agent_interrupted_user_count")))
                inter["monologue_ms"].append(num(st.get("longest_agent_monologue_ms")))
                inter["talk_listen"].append(num(st.get("talk_to_listen_ratio")))
                if (num(st.get("agent_interrupted_user_count")) or 0) >= 2:
                    issues_per_call[cid] += 1

        # transcript signals
        agent_turn_words += [len(words(t)) for t in agent_lines]
        if any(len(words(t)) > 40 for t in agent_lines):
            issues_per_call[cid] += 1
        da = [t for t in user_lines[1:] if DEAD_AIR.search(t)]
        if da:
            dead_air_calls += 1
            dead_air_lines += len(da)
            issues_per_call[cid] += 1
        norm = Counter(re.sub(r"\W+", " ", t.lower()).strip() for t in agent_lines if len(words(t)) >= 4)
        for line, n in norm.items():
            if n >= 2:
                repeats.append((cid, n, line))
                issues_per_call[cid] += 1
        for t in agent_lines:
            for name, pattern in (("markdown", MD_BULLET), ("markdown", MD_INLINE), ("url", URL), ("email", EMAIL),
                                  ("emoji", EMOJI), ("code-read-aloud", CODE), ("machine-date", ISO_DATE)):
                if pattern.search(t):
                    leaks[name] += 1
                    issues_per_call[cid] += 1
        if tts and tts.startswith("sarvam"):
            if any(len(ROMAN_HINDI.findall(t)) >= 3 and not DEVANAGARI.search(t) for t in agent_lines):
                roman_calls += 1
                issues_per_call[cid] += 1

    answered = [c for c in calls if c["answered"]]
    durations = [c["duration"] for c in answered if c["duration"]]
    minutes = sum(durations) / 60 if durations else 0
    cost = sum(c["cost"] or 0 for c in calls)

    capped = []
    if call_cap:
        capped = [c["id"] for c in answered if c["duration"] and c["duration"] >= call_cap - 3]
    elif len(durations) >= 3:
        top = max(durations)
        near = [c["id"] for c in answered if c["duration"] and top - c["duration"] <= 2]
        if top >= 60 and len(near) >= 2:
            capped = near
    for cid in capped:
        issues_per_call[cid] += 1

    stats = {
        "calls": len(calls),
        "answered": len(answered),
        "answer_rate": round(len(answered) / len(calls), 2) if calls else None,
        "voicemail": sum(c["voicemail"] for c in calls),
        "median_answered_duration_s": pct(durations, 50),
        "hangup_by": dict(Counter(c["hangup_by"] for c in calls if c["hangup_by"])),
        "top_hangup_reasons": Counter(c["hangup_reason"] for c in calls if c["hangup_reason"]).most_common(3),
        "cost_cents_per_answered_minute": round(cost / minutes, 2) if minutes else None,
        "latency_ms": {k: {"p50": pct(v, 50), "p95": pct(v, 95), "n": len([x for x in v if x is not None])}
                       for k, v in lat.items()},
        "interruptions_per_call": {
            "user_interrupted_agent": round(sum(filter(None, inter["user_interrupted_agent"])) / max(1, len(inter["user_interrupted_agent"])), 2),
            "agent_interrupted_user": round(sum(filter(None, inter["agent_interrupted_user"])) / max(1, len(inter["agent_interrupted_user"])), 2),
        } if inter["user_interrupted_agent"] else None,
        "longest_monologue_ms_p95": pct(inter["monologue_ms"], 95),
        "talk_to_listen_median": pct(inter["talk_listen"], 50),
        "agent_words_per_turn": {"mean": round(sum(agent_turn_words) / len(agent_turn_words), 1) if agent_turn_words else None,
                                 "p95": pct(agent_turn_words, 95), "max": max(agent_turn_words) if agent_turn_words else None},
        "calls_with_dead_air": dead_air_calls,
        "repeated_agent_lines": [{"call": c, "times": n, "line": l[:80]} for c, n, l in repeats[:5]],
        "unspeakable_in_agent_output": dict(leaks),
        "calls_with_romanised_hindi": roman_calls,
        "calls_at_duration_cap": capped,
        "applied_settings": applied,
        "calls_with_impossible_talk_time": inconsistent,
        "voice_engine": tts,
    }
    p50 = {k: stats["latency_ms"][k]["p50"] for k in ("transcriber", "llm", "synthesizer")}
    if all(v is not None for v in p50.values()):
        stats["processing_ms_p50"] = round(sum(p50.values()))
        wait = sum(num(applied.get(k)) or 0 for k in ("endpointing", "incremental_delay"))
        stats["configured_wait_ms"] = int(wait) or None

    stats["findings"] = findings(stats)
    stats["worst_calls"] = [cid for cid, _ in issues_per_call.most_common(3)]
    return stats


def findings(s: dict) -> list:
    out = []

    def add(rule, sev, msg, fix):
        out.append({"rule": rule, "severity": sev, "message": msg, "fix": fix})

    L = s["latency_ms"]
    for comp, limit in SLOW.items():
        p95 = L[comp]["p95"]
        if p95 is not None and p95 > limit:
            fix = {"llm": "Lower reasoning_effort, try a mini model, shorten the prompt, check the region.",
                   "synthesizer": "Lower buffer_size toward 100–150; check the voice model and region.",
                   "transcriber": "Check the STT region and provider; Indian telephony with Indian servers."}[comp]
            add(f"slow-{comp}", "high" if comp == "llm" else "medium",
                f"{comp} p95 is {int(p95)} ms (Bolna calls over {limit} ms slow; p50 {int(L[comp]['p50'])} ms).", fix)
    if s.get("processing_ms_p50") and s.get("configured_wait_ms"):
        total = int(s["processing_ms_p50"] + s["configured_wait_ms"])
        if total > 1500:
            add("slow-turns", "high",
                f"Typical turn gap is about {total} ms: {s['configured_wait_ms']} ms configured waiting "
                f"(endpointing + incremental_delay) plus {s['processing_ms_p50']} ms processing. People notice gaps over about a second.",
                "Fix the slowest component first, then trim the configured waits.")
    ipc = s.get("interruptions_per_call")
    if ipc and ipc["agent_interrupted_user"] >= 1:
        add("agent-cuts-in", "high", f"The agent interrupts callers {ipc['agent_interrupted_user']} times per call on average.",
            "Raise transcriber endpointing (400–500 ms for callers who pause or read out numbers).")
    if ipc and ipc["user_interrupted_agent"] >= 2:
        add("callers-cut-in", "medium", f"Callers interrupt the agent {ipc['user_interrupted_agent']} times per call.",
            "Usually long agent turns: tighten the prompt's length rule. If it's noise, raise number_of_words_for_interruption or turn on noise cancellation.")
    mono = s.get("longest_monologue_ms_p95")
    if mono and mono > 15000:
        add("monologues", "medium", f"Longest agent monologue reaches {mono / 1000:.0f} s (p95).",
            "Cap turns at one or two sentences in the prompt; lower max_tokens.")
    w = s["agent_words_per_turn"]
    if w["mean"] and w["mean"] > 30:
        add("long-turns", "medium", f"Agent turns average {w['mean']} words (max {w['max']}).", "Add or tighten the brevity rule.")
    if s["calls_with_dead_air"]:
        add("dead-air", "medium", f"{s['calls_with_dead_air']} of {s['answered']} answered calls have callers saying "
            "'hello? are you there?' mid-call.", "Check latency on those turns and slow tool calls; add a short holding line before tools.")
    if s["repeated_agent_lines"]:
        add("loops", "medium", f"The agent repeats itself word for word in {len({r['call'] for r in s['repeated_agent_lines']})} calls.",
            "Add recovery rules: after two failed tries, rephrase, skip, or offer a callback.")
    if s["unspeakable_in_agent_output"]:
        kinds = ", ".join(f"{k} x{v}" for k, v in s["unspeakable_in_agent_output"].items())
        add("unspeakable-output", "high", f"The agent actually said unspeakable text on calls: {kinds}.",
            "Add the 'How you speak' rules and move links and IDs to WhatsApp or SMS.")
    if s["calls_with_romanised_hindi"]:
        add("romanised-output", "high", f"{s['calls_with_romanised_hindi']} calls have the agent writing romanised Hindi to a Sarvam voice.",
            "Add a script rule: Hindi in Devanagari, English words in English letters.")
    if s["calls_at_duration_cap"]:
        add("calls-capped", "high", f"{len(s['calls_at_duration_cap'])} calls end at the maximum call length.",
            "Raise task_config.call_terminate above your longest real call.")
    if s["voicemail"] and s["calls"] and s["voicemail"] / s["calls"] > 0.15:
        add("voicemail-share", "low", f"{s['voicemail']} of {s['calls']} calls hit voicemail.",
            "Turn on voicemail detection and try different calling hours.")
    if s["answer_rate"] is not None and s["calls"] >= 5 and s["answer_rate"] < 0.5:
        add("low-answer-rate", "low", f"Only {int(s['answer_rate'] * 100)}% of calls were answered.",
            "Check calling hours, retries and caller ID. Unknown numbers get ignored.")
    if s.get("calls_with_impossible_talk_time"):
        add("data-quality", "low", f"interruption_stats report more speaking time than the call lasted in "
            f"{len(s['calls_with_impossible_talk_time'])} calls.",
            "Don't rely on talk_to_listen_ratio or speaking times for those calls; use transcripts and interruption counts.")
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda f: order[f["severity"]])


def render(s: dict) -> str:
    L = s["latency_ms"]

    def ms(c):
        return f"p50 {int(L[c]['p50'])} / p95 {int(L[c]['p95'])} ms" if L[c]["p50"] is not None else "no data"

    out = [f"{s['calls']} calls, {s['answered']} answered ({int((s['answer_rate'] or 0) * 100)}%), {s['voicemail']} voicemail, "
           f"median answered call {int(s['median_answered_duration_s'] or 0)} s",
           f"Hung up by: {s['hangup_by'] or 'unknown'}"]
    if s["cost_cents_per_answered_minute"]:
        out.append(f"Cost: {s['cost_cents_per_answered_minute']} cents per answered minute")
    out.append(f"Latency: first audio {ms('ttfa')} | STT {ms('transcriber')} | LLM first token {ms('llm')} | TTS first chunk {ms('synthesizer')}")
    if s.get("processing_ms_p50"):
        out.append(f"Typical turn: {s.get('configured_wait_ms') or '?'} ms configured wait + {s['processing_ms_p50']} ms processing")
    if s["interruptions_per_call"]:
        i = s["interruptions_per_call"]
        out.append(f"Interruptions per call: caller->agent {i['user_interrupted_agent']}, agent->caller {i['agent_interrupted_user']}; "
                   f"longest monologue p95 {int((s['longest_monologue_ms_p95'] or 0) / 1000)} s")
    w = s["agent_words_per_turn"]
    out.append(f"Agent words per turn: mean {w['mean']}, p95 {w['p95']}, max {w['max']}")
    if s["applied_settings"]:
        out.append("Applied settings (usage_breakdown): " + ", ".join(f"{k}={v}" for k, v in s["applied_settings"].items()))
    out.append("")
    for f in s["findings"]:
        out.append(f"[{f['severity'].upper():6}] {f['rule']}: {f['message']}")
        out.append(f"         fix: {f['fix']}")
    if s["repeated_agent_lines"]:
        out.append("")
        out.append("Repeated agent lines:")
        out += [f"  {r['call']}: x{r['times']} \"{r['line']}\"" for r in s["repeated_agent_lines"]]
    if s["worst_calls"]:
        out.append("")
        out.append("Worst calls to listen to: " + ", ".join(s["worst_calls"]))
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("executions_json")
    ap.add_argument("--agent-json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    with open(args.executions_json, encoding="utf-8") as fh:
        execs = load_executions(json.load(fh))
    if not execs:
        print("No calls in this file yet. Make a few test calls (or widen --days when fetching), then run this again.")
        return 0
    agent = None
    if args.agent_json:
        with open(args.agent_json, encoding="utf-8") as fh:
            agent = json.load(fh)
    stats = analyse(execs, agent)
    print(json.dumps(stats, ensure_ascii=False, indent=2, default=str) if args.json else render(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
