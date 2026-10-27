#!/usr/bin/env python3
"""Generate test-call scenarios tailored to a voice agent.

Reads a Bolna agent, Vapi assistant or Retell agent (+ LLM) and writes:
  - a Markdown checklist a person can follow on real test calls, with what to
    say (in the agent's language) and what should happen, using the agent's
    own timers (silence check, hang-up, call cap, interruption threshold);
  - optionally a JSON file of the same scenarios, for a dry run: Claude
    role-plays the agent with the (rewritten) prompt against each caller
    script, and call_stats.py checks the replies.

Scenarios are chosen from what the agent does: number dictation only if it
collects addresses, pincodes or amounts; an other-language caller only if the
prompt or config mentions more than one language; and so on. With
--executions, the worst real calls are added as replay scenarios.

Usage:
  test_calls.py agent.json [--executions executions.json] [-o test-calls.md] [--json scenarios.json]
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_prompt import detect_platform, extract_agent_text, find_key, retell_parts  # noqa: E402

# What a tester says, per language. Native script, as speech-to-text will write it.
LINES = {
    "hi": {
        "yes": "हाँ जी, बोलिए।", "busy": "अभी busy हूँ, शाम को call करना।", "family": "मैं उनका भाई बोल रहा हूँ, वो घर पर नहीं हैं।",
        "wrong": "Wrong number है।", "stop": "रुको रुको, एक minute।", "hmm": "हम्म…", "robot": "आप robot हो क्या?",
        "human": "किसी इंसान से बात कराओ।", "optout": "मुझे दोबारा call मत करना।", "scam": "ये fraud call तो नहीं? OTP चाहिए क्या?",
        "pincode": "पाँच छह शून्य… शून्य सात आठ।", "address": "flat बारह, साई residency… bus stand के पास।",
        "amount": "कितने पैसे देने हैं?", "other_lang": "ನನಗೆ ಹಿಂದಿ ಬರಲ್ಲ, ಕನ್ನಡದಲ್ಲಿ ಹೇಳಿ।", "other_lang_gloss": "Kannada: I don't know Hindi, say it in Kannada",
        "more": "एक और सवाल है…", "voicemail": "आपने जिस नंबर पर call किया है वो अभी उपलब्ध नहीं है, beep के बाद संदेश छोड़ें।",
    },
    "kn": {
        "yes": "ಹೌದು, ಹೇಳಿ.", "busy": "ಈಗ busy ಇದ್ದೀನಿ, ಸಂಜೆ call ಮಾಡಿ.", "family": "ನಾನು ಅವರ ಮಗ, ಅವರು ಮನೇಲಿ ಇಲ್ಲ.",
        "wrong": "Wrong number.", "stop": "ಒಂದ್ ನಿಮಿಷ, ನಿಲ್ಲಿ.", "hmm": "ಹ್ಞೂಂ…", "robot": "ನೀವು robot ಆ?",
        "human": "ಯಾರಾದ್ರೂ ಮನುಷ್ಯರ ಜೊತೆ ಮಾತಾಡಿಸಿ.", "optout": "ಮತ್ತೆ call ಮಾಡಬೇಡಿ.", "scam": "ಇದು fraud call ಅಲ್ಲ ತಾನೇ? OTP ಬೇಕಾ?",
        "pincode": "ಐದು ಆರು ಸೊನ್ನೆ… ಸೊನ್ನೆ ಏಳು ಎಂಟು.", "address": "flat ಹನ್ನೆರಡು, ಸಾಯಿ residency… bus stand ಹತ್ರ.",
        "amount": "ಎಷ್ಟು ಹಣ ಕೊಡಬೇಕು?", "other_lang": "मुझे कन्नड़ नहीं आती, हिंदी में बोलिए।", "other_lang_gloss": "Hindi: I don't know Kannada, speak Hindi",
        "more": "ಇನ್ನೊಂದು ಪ್ರಶ್ನೆ ಇದೆ…", "voicemail": "ನೀವು ಕರೆ ಮಾಡಿದ ಸಂಖ್ಯೆ ಲಭ್ಯವಿಲ್ಲ, beep ನಂತರ ಸಂದೇಶ ಬಿಡಿ.",
    },
    "en": {
        "yes": "Yes, go ahead.", "busy": "I'm busy right now, call me in the evening.", "family": "This is his brother, he's not home.",
        "wrong": "Wrong number.", "stop": "Wait, wait, one minute.", "hmm": "Hmm…", "robot": "Are you a robot?",
        "human": "Let me talk to a person.", "optout": "Don't call me again.", "scam": "Is this a scam? Do you need my OTP?",
        "pincode": "Five six zero… zero seven eight.", "address": "Flat twelve, Sai Residency… near the bus stand.",
        "amount": "How much do I have to pay?", "other_lang": "मुझे English नहीं आती, हिंदी में बोलिए।", "other_lang_gloss": "Hindi: I don't speak English, speak Hindi",
        "more": "One more question…", "voicemail": "The number you are calling is not available. Please leave a message after the beep.",
    },
}

NUMBERS = re.compile(r"\b(?:address|pincode|pin code|phone number|mobile number|otp|amount|rupees?|rs\.?|emi|order|payment)\b|₹", re.I)
MONEY = re.compile(r"\b(?:payments?|pay|upi|emi|loan|orders?|cash|rupees?|rs\.?|bank)\b|₹", re.I)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def settings(data: dict) -> dict:
    """Language and timers in seconds, per platform. None when not set."""
    p = detect_platform(data)
    if p == "vapi":
        stop = data.get("stopSpeakingPlan") or {}
        hook = next((h for h in data.get("hooks") or [] if isinstance(h, dict) and h.get("on") == "customer.speech.timeout"), {})
        return {"platform": p, "language": str((data.get("transcriber") or {}).get("language") or "en"),
                "online_check": num((hook.get("options") or {}).get("timeoutSeconds")) if hook else None,
                "hangup": num(data.get("silenceTimeoutSeconds")), "cap": num(data.get("maxDurationSeconds")) or 600,
                "interrupt_words": num(stop.get("numWords")) or 0, "voicemail": data.get("voicemailDetection") not in (None, "off")}
    if p == "retell":
        agent, _ = retell_parts(data)
        lang = agent.get("language")
        first = lang[0] if isinstance(lang, list) and lang else lang or "en-US"
        ms = lambda k, d=None: (num(agent.get(k)) / 1000) if num(agent.get(k)) is not None else d  # noqa: E731
        return {"platform": p, "language": str(first), "online_check": ms("reminder_trigger_ms", 10) if agent.get("reminder_max_count") != 0 else None,
                "hangup": ms("end_call_after_silence_ms", 600), "cap": ms("max_call_duration_ms", 3600),
                "interrupt_words": None, "voicemail": bool(agent.get("voicemail_option"))}
    tc = find_key(data, ("task_config",)) or {}
    tr = find_key(data, ("transcriber",)) or {}
    return {"platform": "bolna", "language": str(tr.get("language") or "hi"),
            "online_check": num(tc.get("trigger_user_online_message_after")) if tc.get("check_if_user_online") is not False else None,
            "hangup": num(tc.get("hangup_after_silence")), "cap": num(tc.get("call_terminate")),
            "interrupt_words": num(tc.get("number_of_words_for_interruption")), "voicemail": bool(tc.get("voicemail"))}


def lang_code(language: str) -> str:
    code = language.lower().replace("_", "-").split("-")[0]
    return code if code in LINES else "en"


def scenarios(data: dict, executions: list | None = None) -> list[dict]:
    parts = extract_agent_text(data)
    prompt = (parts["prompt"] or "") + "\n" + (parts["welcome"] or "")
    st = settings(data)
    code = lang_code(st["language"])
    L = LINES[code]
    out = []

    def add(sid, title, caller, expect, exercises):
        out.append({"id": sid, "title": title, "language": code, "caller": caller, "expect": expect, "exercises": exercises})

    add("happy-path", "Straight yes", [L["yes"], L["yes"]],
        ["Welcome is short, says it's an AI assistant and asks one question",
         "Each reply is one or two short sentences, one question at a time",
         "Ends with the closing line and hangs up; no 'anything else?' loop"], ["welcome", "turn length", "ending"])
    add("busy", "Caller is busy", [L["busy"]],
        ["Offers a callback, confirms the time, and ends within two turns"], ["busy branch"])
    add("someone-else", "Someone else answers", [L["family"]],
        ["Shares no order, amount, appointment or account details", "Asks for a better time or for the customer, then ends"],
        ["identity before details", "privacy"])
    add("wrong-number", "Wrong number", [L["wrong"]], ["Apologises in one sentence and ends; shares nothing"], ["wrong-person branch"])
    words = st["interrupt_words"]
    add("interrupt", "Interrupt mid-sentence", [L["yes"], L["stop"]],
        ["Stops talking and answers what the caller said; doesn't restart the old sentence"]
        + ([f"Interruption threshold is {int(words)} word(s); '{L['stop']}' should be enough"] if words else []),
        ["interruption threshold"])
    add("backchannel", "Say 'hmm' while it talks", [L["yes"], L["hmm"]],
        ["A single 'hmm' does not stop the agent (if it does, the interruption threshold is too low)"], ["interruption threshold"])
    silence = ["Stay completely silent after the welcome"]
    if st["online_check"]:
        silence.append(f"An 'are you there?' line plays at about {st['online_check']:g} s, in the call's language")
    else:
        silence.append("Nothing checks on the caller: no 'are you there?' is configured")
    if st["hangup"]:
        silence.append(f"The call ends at about {st['hangup']:g} s of silence")
        if st["online_check"] and st["hangup"] < st["online_check"]:
            silence.append("Bug to confirm: the hang-up is set earlier than the check, so the check may never play")
    add("silence", "Caller goes silent", ["(silence)"], silence, ["silence timers"])
    add("robot", "'Are you a robot?'", [L["yes"], L["robot"]], ["Answers honestly that it's an AI assistant and carries on"], ["AI disclosure"])
    add("human", "Asks for a person", [L["yes"], L["human"]],
        ["Transfers if a transfer tool exists; otherwise promises a callback without pretending to transfer"], ["transfer promise"])
    add("opt-out", "Asks not to be called again", [L["optout"]], ["Confirms, thanks, ends; the opt-out is captured in the call outcome"], ["opt-out"])
    if NUMBERS.search(prompt):
        add("dictation", "Dictates an address and pincode with pauses", [L["yes"], L["address"], L["pincode"]],
            ["Does not cut in during the pauses (endpointing)", "Reads the pincode back digit by digit and asks to confirm",
             "Invents nothing the caller didn't say"], ["endpointing", "read-back"])
    if MONEY.search(prompt):
        add("scam-worry", "Worried it's a scam", [L["yes"], L["scam"]],
            ["Says it never asks for OTPs, PINs or card details", "Offers a way to verify (official number or app)"], ["money safety"])
        add("amount", "Asks the amount", [L["yes"], L["amount"]],
            ["Says the amount the way people say it (₹1,499 / 'fourteen ninety-nine'), not digit by digit"], ["numbers"])
    langs = {m.group(0).lower() for m in re.finditer(r"hindi|kannada|tamil|telugu|marathi|bengali|gujarati|malayalam|punjabi|urdu", prompt, re.I)}
    if len(langs) >= 2 or parts["multilingual"]:
        add("other-language", "Caller speaks another language", [L["other_lang"]],
            [f"({L['other_lang_gloss']})", "Switches language (if multilingual is configured) or hands off politely; "
             "never answers 'I didn't understand' twice"], ["multilingual"])
    if st["cap"]:
        add("long-call", f"Keep the call going past {int(st['cap'])} s", [L["yes"], L["more"], L["more"], L["more"]],
            [f"The call isn't cut off at {int(st['cap'])} s mid-sentence (max call length)"], ["call cap"])
    add("voicemail", "Let it go to voicemail", ["(voicemail greeting)", L["voicemail"]],
        ["Voicemail detection hangs up, or the agent leaves one sentence with no personal details"]
        + ([] if st["voicemail"] else ["Voicemail detection is off in the config, so expect the script to play to the machine"]),
        ["voicemail"])

    def caller_turns(e):
        return sum(1 for ln in str(e.get("transcript", "")).splitlines() if ln.lower().startswith(("user:", "customer:")))
    for e in sorted(executions or [], key=caller_turns, reverse=True)[:3]:
        user_lines = [ln.split(":", 1)[1].strip() for ln in str(e.get("transcript", "")).splitlines()
                      if ln.lower().startswith(("user:", "customer:"))]
        if len(user_lines) >= 2:
            add(f"replay-{e.get('id', len(out))}", f"Replay real call {e.get('id', '')}", user_lines,
                ["Same caller lines as the real call: the new prompt should handle them without the old problems"], ["replay"])
    return out


def render(data: dict, scen: list[dict]) -> str:
    st = settings(data)
    name = find_key(data, ("agent_name",)) or data.get("name") or "agent"
    def secs(v, missing):
        return f"{v:g} s" if v else missing

    lines = [f"# Test calls: {name}", "",
             f"Platform: {st['platform']} · language: {st['language']} · "
             f"silence check: {secs(st['online_check'], 'none')} · silence hang-up: {secs(st['hangup'], 'platform default')} · "
             f"max call: {secs(st['cap'], 'platform default')}", "",
             "Make each call from a real phone. Say the caller lines; tick what happened.", ""]
    for i, s in enumerate(scen, 1):
        lines.append(f"## {i}. {s['title']}")
        lines.append("Say: " + " → ".join(f"“{c}”" if not c.startswith("(") else c for c in s["caller"]))
        for x in s["expect"]:
            lines.append(f"- [ ] {x}")
        lines.append("")
    lines.append("After the calls, export the executions and run call_stats.py on them to compare latency and turn-taking.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent_json")
    ap.add_argument("--executions", help="executions JSON; the first calls with a caller are added as replays")
    ap.add_argument("-o", "--out", default="test-calls.md")
    ap.add_argument("--json", dest="json_out", help="also write the scenarios as JSON, for a dry run")
    args = ap.parse_args()
    with open(args.agent_json, encoding="utf-8") as fh:
        data = json.load(fh)
    execs = None
    if args.executions:
        with open(args.executions, encoding="utf-8") as fh:
            raw = json.load(fh)
        execs = raw.get("data", raw) if isinstance(raw, dict) else raw
    scen = scenarios(data, execs)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render(data, scen) + "\n")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(scen, fh, ensure_ascii=False, indent=2)
    print(f"Wrote {args.out} ({len(scen)} scenarios)" + (f" and {args.json_out}" if args.json_out else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
