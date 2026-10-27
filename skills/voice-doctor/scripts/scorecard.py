#!/usr/bin/env python3
"""Make a shareable before/after scorecard for a voice-agent checkup.

Writes a 1200x630 SVG card (the size social sites preview) with the
speakability and config scores, before and after, and the top problems fixed
in plain words. Optionally prints a shields.io badge for a README.

Usage:
  scorecard.py agent.json [--after agent.fixed.json] [-o scorecard.svg] [--badge]

With only one agent, the card shows its current scores and top problems.
To get a PNG: chrome --headless --window-size=1200,630 --screenshot=card.png file://$PWD/scorecard.svg
(or rsvg-convert, or open the SVG in a browser and screenshot it).
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import quote
from xml.sax.saxutils import escape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_config import audit  # noqa: E402
from lint_prompt import extract_agent_text, find_key, lint  # noqa: E402

# What each finding means to a caller, for people who never read the report.
RULE_LABELS = {
    "call-cut-off": "Calls cut off mid-conversation",
    "endpointing-too-low": "Agent talked over callers",
    "endpointing-too-high": "Long pause before every reply",
    "turn-wait-high": "Long pause before every reply",
    "delay-high": "Long pause before every reply",
    "llm-reasoning-effort": "Slow replies while the model 'thinks'",
    "tts-buffer-large": "Voice slow to start speaking",
    "interrupt-too-easy": "A cough stopped the agent mid-sentence",
    "interrupt-too-hard": "Callers couldn't interrupt",
    "silence-hangup-short": "Hung up on callers who paused",
    "silence-hangup-before-check": "Hung up before asking 'are you there?'",
    "default-hangup-check": "'Thank you' could hang up the call",
    "voicemail-off": "Read the script to voicemail",
    "multilingual-off": "Other languages misheard and mispronounced",
    "multi-language-one-voice": "Other languages misheard and mispronounced",
    "tts-language-unsupported": "Voice couldn't speak the caller's language",
    "stt-language-unsupported": "Couldn't understand the caller's language",
    "tts-voice-version": "Voice id didn't exist on the model",
    "tts-voice-missing": "No real voice configured",
    "tts-language-missing": "Voice had no language set",
    "online-check-language": "'Are you there?' in the wrong language",
    "romanised-indic": "Hindi written in English letters",
    "no-script-rule": "Hindi written in English letters",
    "stiff-hindi": "Textbook Hindi instead of how people talk",
    "written-kannada": "Written Kannada instead of spoken",
    "no-output-style-rule": "Markdown and lists read aloud",
    "markdown": "Markdown read aloud",
    "url-in-prompt": "Links read aloud",
    "url": "Links read aloud",
    "email-in-prompt": "Email addresses read aloud",
    "code-read-aloud": "Order IDs read aloud",
    "no-brevity-rule": "Long monologues",
    "long-welcome": "Long welcome before the caller can speak",
    "stacked-questions": "Two questions at once",
    "no-ai-disclosure": "Didn't say it's an AI",
    "undefined-variable": "Placeholders read out literally",
    "placeholder-text": "Template leftovers in the prompt",
    "webhook-placeholder": "Call outcomes went nowhere",
    "no-outcome-capture": "Call outcomes went nowhere",
    "transfer-promise": "Promised a transfer it couldn't make",
    "no-calling-hours": "Could ring people late at night",
    "no-ending-rule": "Didn't know when to end the call",
}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
# Lead with what makes an agent sound robotic or broken to a caller.
SHOWCASE = ["romanised-indic", "call-cut-off", "no-output-style-rule", "endpointing-too-low", "code-read-aloud",
            "url-in-prompt", "multilingual-off", "multi-language-one-voice", "tts-language-unsupported",
            "default-hangup-check", "llm-reasoning-effort", "tts-voice-version", "long-welcome", "no-brevity-rule"]


def label(rule: str) -> str:
    return RULE_LABELS.get(rule, rule.replace("-", " ").capitalize())


def checkup(agent: dict) -> dict:
    a = audit(agent, None)
    findings = [(f.severity, f.rule) for f in a.findings]
    out = {"config": a.score, "speakability": None}
    parts = extract_agent_text(agent)
    if isinstance(parts["prompt"], str):
        r = lint(parts["prompt"], parts["welcome"], None, parts["tts"], parts["multilingual"], parts["platform"])
        out["speakability"] = r.score
        findings += [(f.severity, f.rule) for f in r.findings]
    out["findings"] = findings
    out["name"] = find_key(agent, ("agent_name",)) or agent.get("name") or "voice agent"
    return out


def top_labels(findings, exclude=(), n=3):
    seen, out = set(), []
    rank = {r: i for i, r in enumerate(SHOWCASE)}
    for sev, rule in sorted(findings, key=lambda x: (rank.get(x[1], len(SHOWCASE)), SEVERITY_ORDER[x[0]])):
        lab = label(rule)
        if sev == "low" or rule in exclude or lab in seen:
            continue
        seen.add(lab)
        out.append(lab)
        if len(out) == n:
            break
    return out


def colour(score) -> str:
    if score is None:
        return "#8b8b99"
    return "#3ddc84" if score >= 85 else "#f5c542" if score >= 60 else "#ff5c5c"


def overall(c: dict) -> int:
    vals = [v for v in (c["config"], c["speakability"]) if v is not None]
    return round(sum(vals) / len(vals))


def badge(score: int) -> str:
    col = "brightgreen" if score >= 90 else "green" if score >= 75 else "yellow" if score >= 60 else "orange" if score >= 40 else "red"
    return f"https://img.shields.io/badge/{quote('voice--doctor')}-{score}%2F100-{col}"


def svg(before: dict, after: dict | None) -> str:
    W, H = 1200, 630
    name = escape(str(before["name"])[:48])
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        '<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#14121f"/><stop offset="1" stop-color="#241b3d"/></linearGradient></defs>',
        f'<rect width="{W}" height="{H}" fill="url(#bg)"/>',
        '<g font-family="Inter, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif">',
        '<text x="64" y="92" fill="#b9a6ff" font-size="30" font-weight="600">voice-doctor checkup</text>',
        f'<text x="64" y="150" fill="#ffffff" font-size="44" font-weight="700">{name}</text>',
    ]

    def block(x, title, b, a):
        parts.append(f'<text x="{x}" y="232" fill="#a9a6b8" font-size="26">{title}</text>')
        if a is None:
            parts.append(f'<text x="{x}" y="318" fill="{colour(b)}" font-size="84" font-weight="800">{b if b is not None else "–"}</text>')
        else:
            parts.append(f'<text x="{x}" y="318" font-size="84" font-weight="800">'
                         f'<tspan fill="{colour(b)}">{b}</tspan><tspan fill="#6f6a85" font-size="60" dx="18">→</tspan>'
                         f'<tspan fill="{colour(a)}" dx="18">{a}</tspan></text>')

    a = after or {}
    block(64, "Speakability", before["speakability"], a.get("speakability") if after else None)
    block(620, "Config", before["config"], a.get("config") if after else None)

    if after:
        fixed_rules = {r for _, r in before["findings"]} - {r for _, r in after["findings"]}
        items = top_labels([(s, r) for s, r in before["findings"] if r in fixed_rules])
        heading, mark, mark_col = "Fixed", "✓", "#3ddc84"
    else:
        items = top_labels(before["findings"])
        heading, mark, mark_col = "Top problems", "•", "#ff8a8a"
    parts.append(f'<text x="64" y="398" fill="#a9a6b8" font-size="26">{heading}</text>')
    for i, item in enumerate(items):
        y = 446 + i * 46
        parts.append(f'<text x="64" y="{y}" font-size="30"><tspan fill="{mark_col}">{mark}</tspan>'
                     f'<tspan fill="#ffffff" dx="14">{escape(item)}</tspan></text>')
    parts += [
        f'<text x="64" y="{H - 40}" fill="#6f6a85" font-size="24">github.com/dakshinsiva/voice-doctor</text>',
        f'<text x="{W - 64}" y="{H - 40}" fill="#6f6a85" font-size="24" text-anchor="end">Voice agents for India · Bolna · Vapi · Retell · LiveKit · Pipecat</text>',
        "</g></svg>",
    ]
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent_json", help="the agent before fixes (or the only agent)")
    ap.add_argument("--after", help="the agent after fixes, e.g. agent.fixed.json from apply_changes.py")
    ap.add_argument("-o", "--out", default="scorecard.svg")
    ap.add_argument("--badge", action="store_true", help="also print a shields.io badge for a README")
    args = ap.parse_args()

    with open(args.agent_json, encoding="utf-8") as fh:
        before = checkup(json.load(fh))
    after = None
    if args.after:
        with open(args.after, encoding="utf-8") as fh:
            after = checkup(json.load(fh))
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(svg(before, after))

    final = after or before
    print(f"Wrote {args.out}")
    if after:
        print(f"Speakability {before['speakability']} -> {after['speakability']} · Config {before['config']} -> {after['config']}")
    else:
        print(f"Speakability {before['speakability']} · Config {before['config']}")
    if args.badge:
        score = overall(final)
        print(f"Badge ({score}/100): ![voice-doctor score]({badge(score)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
