#!/usr/bin/env python3
"""Build speech-to-text keywords and a pronunciation watchlist for an agent.

Finds the names and acronyms a voice agent depends on (brand, clinic and
product names, place names, acronyms like COD, UPI, EMI) in its prompt,
welcome message and name, and produces:
  - a keyword list for the platform's speech-to-text boosting field
    (Bolna transcriber.keywords, Vapi transcriber.keyterm, Retell
    boosted_keywords), merged with what's already configured, with wasted
    entries flagged;
  - a pronunciation watchlist for the voice: acronyms that may be read as a
    word ("COD" like the fish) and brand names to listen for, with where each
    platform takes a pronunciation fix;
  - optionally a change file for apply_changes.py.

Usage:
  vocab.py agent.json [--max 20] [--changes vocab-changes.json] [--json]
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_prompt import detect_platform, extract_agent_text, find_key, retell_parts  # noqa: E402

# Words trimmed from the edges of a candidate name: grammar, instructions, greetings,
# romanised Hindi, platform names.
TRIM = set("""
a an the this that these those it its is are be do does don't never always you your yours we our us they their them he she his her
i if when then else and or but so to of in on at for with from by as about into after before while until my new
say tell ask remind confirm greet offer thank keep use give read speak switch end handle
yes no ok okay hello hi namaste namaskar dhanyavaad dhanyawaad kripya ji sir madam mr mrs ms dr
hindi english kannada tamil telugu marathi bengali gujarati malayalam punjabi urdu odia hinglish indian
bolna vapi retell sarvam deepgram cartesia elevenlabs openai plivo exotel twilio gpt
main mein aap aapka aapki aapke aapne kya haan nahi nahin theek thik bilkul koi ek do teen acha achha accha
monday tuesday wednesday thursday friday saturday sunday
""".split())
# Generic words: fine inside a name ("Acme Store", "SmileCare Dental Clinic"), not a keyword alone.
GENERIC = TRIM | set("""
role steps step rules rule important language languages details detail flow call calls situations limits ending facts
how who what why which where note notes example examples
customer customers client clients patient patients caller callers user users agent assistant ai human person team voice
order orders plan target name amount address date time day next last first second third test demo default
cash delivery online store clinic doctor appointment payment pay link website email whatsapp sms
rs rupees total product items item expected due borrower positive negative perfect questions greeting
""".split())
PERSONA = re.compile(r"(?i:\b(?:you are|i am|i'm|this is|main|मैं))[ \t]+([A-Z][a-z]+|[\u0900-\u0DFF]+)")
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,6}\b")
# Acronyms people normally say letter by letter; a voice may read them as a word instead.
READ_AS_WORD_RISK = {"COD", "EMI", "KYC", "PAN", "GST", "NEFT", "IMPS", "SIP", "NACH"}
EMPHASIS = {"NOT", "OR", "AND", "THIS", "DO", "NO", "YES", "ONLY", "ALL", "ANY", "THE", "IF", "MUST", "NEVER", "ALWAYS", "DONT", "END"}
PLAIN_ACRONYMS = {"AI", "OK", "OTP", "UPI", "SMS", "ID", "PIN", "IST", "AM", "PM", "TV", "USA", "UK", "BP", "ATM"}
TITLE_PHRASE = re.compile(r"\b(?:[A-Z][a-z]+|[A-Z][a-z]*[A-Z][A-Za-z]+)(?:[ -](?:[A-Z][a-z]+|[A-Z][a-z]*[A-Z][A-Za-z]+|&))*\b")
CAMEL = re.compile(r"^[A-Z][a-z]+[A-Z][A-Za-z]*$")


def candidates(text: str, name: str = "") -> tuple[Counter, Counter]:
    names, acronyms = Counter(), Counter()
    for line in (text + "\n" + name).splitlines():
        if line.lstrip().startswith("#"):
            continue  # markdown headings are structure
        line = re.sub(r"\{\{?\s*\w+\s*\}?\}|https?://\S+|\S+@\S+", " ", line)
        line = re.sub(r"\*\*[^*]+\*\*", " ", line)  # bold text is labels and emphasis
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])?\s*[\w ]{1,30}:(?=\s)", " ", line)  # "- Label:" prefixes
        for m in ACRONYM.finditer(line):
            tok = m.group(0)
            if tok in PLAIN_ACRONYMS or tok in EMPHASIS or tok.isdigit() or (len(tok) > 5 and not re.search(r"\d", tok)):
                continue  # long all-caps words are shouting (REMOVED, IMPORTANT), not acronyms
            acronyms[tok] += 1
        for m in TITLE_PHRASE.finditer(line):
            phrase = m.group(0).strip(" -&")
            words = [w for w in re.split(r"[ -]", phrase) if w and w != "&" and not w.isupper()]
            while words and words[0].lower() in TRIM:
                words.pop(0)
            while words and words[-1].lower() in TRIM:
                words.pop()
            if not words:
                continue
            phrase = " ".join(words)
            before = line[: m.start()]
            at_start = (not before.strip(" \t-*•0123456789.)") or re.search(r"(?:[.!?:]\s+|[\"“'(→]\s*)$", before)) is not None
            if len(words) == 1 and at_start and not CAMEL.match(words[0]):
                continue  # a sentence-initial capital is usually just grammar
            if all(w.lower() in GENERIC for w in words):
                continue
            names[phrase] += 1
    return names, acronyms


def existing_keywords(data: dict, platform: str) -> list[str]:
    if platform == "vapi":
        tr = data.get("transcriber") or {}
        kw = tr.get("keyterm") or tr.get("keywords") or []
        return [str(k).split(":")[0] for k in kw]
    if platform == "retell":
        agent, _ = retell_parts(data)
        return [str(k) for k in agent.get("boosted_keywords") or []]
    tr = find_key(data, ("transcriber",)) or {}
    return [k.strip() for k in str(tr.get("keywords") or "").split(",") if k.strip()]


def build(data: dict, limit: int = 20) -> dict:
    platform = detect_platform(data)
    parts = extract_agent_text(data)
    name = str(find_key(data, ("agent_name",)) or data.get("name") or "")
    text = (parts["prompt"] or "") + "\n" + (parts["welcome"] or "")
    names, acronyms = candidates(text, name)
    have = existing_keywords(data, platform)
    personas = {m.group(1).lower() for m in PERSONA.finditer(text)}
    said_by_agent = {"namaste", "namaskar", "dhanyavaad", "dhanyawaad", "shukriya", "hello", "thank you"} | personas
    wasted = [k for k in have if k.lower() in said_by_agent]
    phrases = [n for n, _ in names.most_common() if n.lower() not in personas]
    # Drop a single word that's already inside a longer name ("Acme" when "Acme Store" is listed).
    phrases = [n for n in phrases if not any(n != o and f" {n} " in f" {o} " for o in phrases + have)]
    ranked = phrases + [a for a, _ in acronyms.most_common()]
    keep = [k for k in have if k not in wasted]
    keywords = list(dict.fromkeys(keep + ranked))[:limit]

    watch = []
    for a, _ in acronyms.most_common():
        if a in READ_AS_WORD_RISK:
            watch.append({"term": a, "risk": "may be read as a word", "quick_fix": f"write it as '{' '.join(a)}' or spell it out in the prompt"})
        elif re.search(r"\d", a):
            watch.append({"term": a, "risk": "letters and digits", "quick_fix": "avoid saying it; send it by message, or spell it in short groups"})
    for n, _ in names.most_common(6):
        watch.append({"term": n, "risk": "brand or place name", "quick_fix": "listen on a test call; add a pronunciation entry if it's wrong"})

    field = {"bolna": "agent_config.tasks[0].tools_config.transcriber.keywords (comma-separated)",
             "vapi": "transcriber.keyterm (list; Deepgram nova-3)", "retell": "agent.boosted_keywords (list)"}.get(platform, "keywords")
    pron = {"bolna": "Sarvam Bulbul v3/v4 Flash: a pronunciation dictionary (dict_id); Cartesia: pronunciation_dict_id; ElevenLabs: alias rules",
            "vapi": "11labs: pronunciation dictionary alias rules; Cartesia: pronunciation dictionary; or respell the word in the prompt",
            "retell": "agent.pronunciation_dictionary [{word, alphabet: ipa|cmu, phoneme}]"}.get(platform, "respell the word in the prompt")
    notes = []
    tr = find_key(data, ("transcriber",)) or {}
    if platform == "bolna" and str(tr.get("provider", "")).lower() == "sarvam" and str(tr.get("model", "")) != "saaras:v4":
        notes.append("Sarvam only uses keywords on saaras:v4; on this model they are ignored.")
    if platform == "bolna" and str(tr.get("provider", "")).lower() == "sarvam":
        notes.append("Sarvam may return boosted English terms in Devanagari; check transcripts.")
    if len(keywords) > 20 and platform == "bolna":
        notes.append("Bolna recommends 10–20 terms you've actually seen misheard; trim after a few calls.")
    notes.append("Names that change per call (customers, patients) can't go in a static list; test common ones on calls.")
    return {"platform": platform, "field": field, "keywords": keywords, "existing": have, "wasted": wasted,
            "pronunciation_watchlist": watch, "pronunciation_fix": pron, "notes": notes}


def change_file(data: dict, result: dict) -> dict:
    kw = result["keywords"]
    if result["platform"] == "vapi":
        return {"transcriber": {"keyterm": kw}}
    if result["platform"] == "retell":
        return {"agent": {"boosted_keywords": kw}}
    change = {"tasks": [{"tools_config": {"transcriber": {"keywords": ", ".join(kw)}}}]}
    return {"agent_config": change} if "agent_config" in data else change


def render(r: dict) -> str:
    out = [f"Speech-to-text keywords ({r['platform']}: {r['field']}):", "  " + (", ".join(r["keywords"]) or "(none found)")]
    if r["wasted"]:
        out.append("Drop from the current list (words the agent says, not the caller): " + ", ".join(r["wasted"]))
    out.append("")
    out.append("Pronunciation watchlist (listen on a test call):")
    for w in r["pronunciation_watchlist"] or [{"term": "(nothing obvious)", "risk": "", "quick_fix": ""}]:
        out.append(f"  - {w['term']}: {w['risk']}" + (f". Fix: {w['quick_fix']}" if w["quick_fix"] else ""))
    out.append(f"Where pronunciation fixes go: {r['pronunciation_fix']}")
    out += [""] + [f"Note: {n}" for n in r["notes"]]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent_json")
    ap.add_argument("--max", type=int, default=20, help="keyword list size (default 20)")
    ap.add_argument("--changes", help="write a change file for apply_changes.py")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    with open(args.agent_json, encoding="utf-8") as fh:
        data = json.load(fh)
    result = build(data, args.max)
    if args.changes:
        with open(args.changes, "w", encoding="utf-8") as fh:
            json.dump(change_file(data, result), fh, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(result))
    if args.changes and not args.json:
        print(f"\nWrote {args.changes}; apply it with apply_changes.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
