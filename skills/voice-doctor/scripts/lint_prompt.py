#!/usr/bin/env python3
"""Speakability linter for voice-agent prompts.

Finds things that sound wrong when a voice engine reads them out on a call:
markdown, links, machine-format numbers, wrong script for Indic voices, long
sentences, stacked questions, a long welcome message, missing voice rules and
missing per-call variables.

Number and script rules depend on the voice engine (--tts). Sarvam Bulbul v4
Flash and Cartesia want conventional written numbers (₹5,00,000); ElevenLabs
Flash wants them spelled out. With --agent-json the engine is read from the
Bolna synthesizer config.

It is a heuristic first pass. It can't understand meaning, so treat findings as
leads to check, not verdicts.

Usage:
  lint_prompt.py PROMPT_FILE [--welcome TEXT_OR_FILE] [--tts ENGINE] [--vars a,b] [--json]
  lint_prompt.py --agent-json agent.json [--vars a,b] [--json]

PROMPT_FILE may be "-" for stdin. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field

SEVERITY_COST = {"high": 8, "medium": 4, "low": 1}
WORDS_PER_SECOND = 2.5  # rough conversational TTS pace

# How each engine wants numbers written. "written": conventional forms with
# Indian grouping (₹1,499, 18 October). "words": spelled out by the model.
# "test": vendor docs are unclear, so check on a real call.
TTS_ENGINES = {
    "sarvam-v4": {"numbers": "written", "native_script": True, "label": "Sarvam Bulbul v4 Flash"},
    "sarvam-v3": {"numbers": "test", "native_script": True, "label": "Sarvam Bulbul v3"},
    "sarvam-v2": {"numbers": "words", "native_script": True, "label": "Sarvam Bulbul v2"},
    "cartesia": {"numbers": "written", "native_script": False, "label": "Cartesia Sonic"},
    "elevenlabs": {"numbers": "words", "native_script": False, "label": "ElevenLabs"},
    "generic": {"numbers": "words", "native_script": False, "label": "unknown engine"},
}


@dataclass
class Finding:
    rule: str
    severity: str  # high | medium | low
    message: str
    fix: str
    line: int | None = None
    snippet: str = ""
    where: str = "prompt"  # prompt | welcome | spoken-line


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def add(self, *args, **kwargs):
        self.findings.append(Finding(*args, **kwargs))

    def has(self, rule: str) -> bool:
        return any(f.rule == rule for f in self.findings)

    @property
    def score(self) -> int:
        return max(0, 100 - sum(SEVERITY_COST[f.severity] for f in self.findings))


# --- patterns -------------------------------------------------------------

URL = re.compile(r"https?://\S+|www\.\S+|(?<![@\w.])[\w-]+\.(?:com|in|org|net|io|co|ai|app)\b(?:/\S*)?", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?:\+91[\s-]?)?\b[6-9]\d{4}[\s-]?\d{5}\b|\b\d{10,}\b")
CODE = re.compile(r"#\s?[A-Z0-9][A-Z0-9-]{4,}|\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9]{2,}-?[A-Z0-9-]{3,}\b")
CURRENCY = re.compile(r"(?:₹|\bRs\.?|\bINR)\s?\d[\d,]*(?:\.\d+)?|\b\d{1,2},\d{2},\d{3}\b", re.I)
SLASH_DATE = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+(?:Z|[+-]\d{2}:?\d{2})?)?\b")
TIME = re.compile(r"\b\d{1,2}:\d{2}\s?(?:am|pm)?\b", re.I)
BIG_RAW_NUMBER = re.compile(r"(?<![\d,.])\d{5,9}(?![\d,])")
UNIT = re.compile(r"\b\d+(?:\.\d+)?\s?(?:kg|g|gm|mg|mcg|ml|l|km|cm|mm|kcal|cal|hrs?|mins?)\b", re.I)
ABBREV = re.compile(r"\b(?:e\.g\.|i\.e\.|etc\.|approx\.|vs\.?|Dr\.|Mr\.|Mrs\.|Ms\.|No\.|qty\.?|pls)(?=\s|$)", re.I)
SYMBOL = re.compile(r"[&%@=~<>→←•|]|(?<=\w)/(?=[A-Za-z])")
BRACKET = re.compile(r"[()\[\]]")
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U0001F000-\U0001F2FF☀-➿⭐⭕️]")
MD_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.M)
MD_INLINE = re.compile(r"\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|^\s*#{1,6}\s", re.M)
VAR = re.compile(r"\{\{\s*([\w.]+)\s*\}\}|\{\s*([A-Za-z_][\w.]*)\s*\}")
SPEAKER_LINE = re.compile(
    r"^\s*(?:agent|assistant|ai|bot|say|sample|example(?: response)?|response)\s*[:\-]\s*(.+)$",
    re.I | re.M,
)
QUOTED = re.compile(r"\"([^\"\n]{12,})\"|“([^”\n]{12,})”")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?।])\s+")
FORMATTED_VAR_HINT = re.compile(
    r"date|time|day|amount|price|fee|cost|total|phone|mobile|number|dob|due|slot|appointment|emi|balance", re.I)
# Common Hindi words written in Latin script: a sign the model or author is using romanised Hindi.
ROMAN_HINDI = re.compile(
    r"\b(?:aap|aapka|aapki|aapke|hai|hain|kya|nahi|nahin|hoon|hun|kripya|dhanyavaad|dhanyavad|namaste|"
    r"theek|thik|kal|abhi|bataiye|batayein|karna|karein|kijiye|raha|rahi|rahe|wala|wali|mein|ki|ke|ko)\b",
    re.I,
)
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
INDIC_SCRIPT = re.compile(r"[ऀ-෿]")
# Formal "IVR Hindi" and translated idioms that sound scripted on a call.
STIFF_HINDI = re.compile(r"अवगत|सुनिश्चित|प्रतीक्षा|सफलतापूर्वक|करना चाहेंगे|करना चाहेंगी|आपका दिन शुभ हो|आपका आदेश")
# Written-register Kannada; spoken equivalents are ಮಾಡ್ತೀನಿ, ಮಾತಾಡಬಹುದಾ, ಇದ್ರೆ, ಆಗುತ್ತೆ.
WRITTEN_KANNADA = re.compile(r"ಮಾಡುತ್ತೇನೆ|ಮಾಡುತ್ತಿದ್ದೇನೆ|ಮಾಡಿದ್ದೇನೆ|ಮಾತನಾಡಬಹುದೇ|ಇದ್ದರೆ|ಆಗುತ್ತದೆ|ಕರೆ ಮಾಡ")

INDIAN_LANGUAGES = [
    "hindi", "kannada", "tamil", "telugu", "marathi", "bengali", "bangla", "gujarati",
    "malayalam", "punjabi", "odia", "assamese", "urdu",
]

PRESENCE_RULES = [
    (
        "no-output-style-rule",
        r"markdown|bullet|\blists?\b|emoji|formatting|plain (?:spoken )?(?:text|sentences)|out loud|aloud|spoken|speak naturally",
        "high",
        "Nothing tells the model its words will be spoken. Chat-tuned models default to lists and bold text, which voice engines read as noise or skip.",
        "Add a 'How you speak' section: plain spoken sentences only, no lists, markdown, emojis or symbols.",
    ),
    (
        "no-brevity-rule",
        r"short|brief|concise|one or two sentences|1-2 sentences|two sentences|2 sentences|under \d+ words|few words",
        "high",
        "No length limit. Long turns are the main reason callers interrupt, talk over the agent, or hang up.",
        "Say: keep every reply to one or two short sentences, then stop and let the caller talk.",
    ),
    (
        "no-one-question-rule",
        r"one question|single question|ask one|one thing at a time",
        "medium",
        "No 'one question at a time' rule. Stacked questions get one answer and the rest are lost.",
        "Add: ask exactly one question per turn and wait for the answer.",
    ),
    (
        "no-ending-rule",
        r"end (?:the )?call|hang ?up|end_call|disconnect|wrap up|say goodbye|close the call",
        "medium",
        "No explicit ending. Agents without one loop on 'anything else?' and burn minutes.",
        "List when to end the call (task done, caller asks, wrong person, voicemail) and the closing line.",
    ),
    (
        "no-not-understood-rule",
        r"didn'?t (?:catch|understand|hear)|could ?n[o']t (?:hear|understand)|unclear|repeat|samajh nahi|dobara|again\?",
        "low",
        "No recovery line for when speech-to-text mishears or the line is noisy.",
        "Add: if an answer is unclear, say so briefly and ask again in simpler words; after two tries, move on or offer a callback.",
    ),
    (
        "no-busy-or-wrong-person-rule",
        r"wrong (?:number|person)|busy|not a good time|bad time|voicemail|answering machine|someone else",
        "low",
        "No path for 'I'm busy', 'wrong number' or voicemail, a big share of real outbound calls.",
        "Add short branches: busy -> offer a time and end; wrong person -> apologise and end; voicemail -> one sentence and end.",
    ),
]

NUMBER_RULE = {
    "words": (
        r"spell out|in words|digit by digit|say (?:the )?numbers|numbers as words|pronounc|read (?:out|back)",
        "medium",
        "No rule for saying numbers, money, dates or times. This engine reads '₹1,500' or '17:30' unreliably.",
        "Add a numbers rule: money, dates and times in words the way people say them; phone numbers and OTPs digit by digit in small groups.",
    ),
    "written": (
        r"digit|group|spell|read (?:out|back)|one by one|pronounc",
        "low",
        "No rule for phone numbers, OTPs and codes. This engine reads ordinary written numbers well, but long digit strings come out as one huge number.",
        "Add: read phone numbers and OTPs digit by digit in small groups; never read order IDs, send them by message.",
    ),
    "test": (
        r"spell out|in words|digit|group|read (?:out|back)|pronounc",
        "medium",
        "No rule for saying numbers. Vendor docs don't say how this engine reads written numbers.",
        "Test '₹1,499' and 'one thousand four hundred ninety-nine rupees' on a real call, then add a rule for whichever sounds right.",
    ),
}


# --- helpers --------------------------------------------------------------

def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def short(s: str, n: int = 80) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def spoken_segments(prompt: str) -> list[tuple[int, str]]:
    """Lines in the prompt that the agent is likely to say verbatim."""
    segs = [(m.start(1), m.group(1)) for m in SPEAKER_LINE.finditer(prompt)]
    for m in QUOTED.finditer(prompt):
        text = m.group(1) or m.group(2)
        if len(words(text)) >= 4:
            segs.append((m.start(), text))
    seen, out = set(), []
    for start, text in sorted(segs):
        key = line_of(prompt, start)
        if key not in seen:
            seen.add(key)
            out.append((start, text))
    return out


def number_checks(policy: str):
    """Spoken-text number checks for an engine's number policy."""
    always = [
        (ISO_DATE, "machine-date", "medium", "Machine-format date or timestamp. Read out as digits and dashes.",
         "Pass dates as speech: 'Saturday, 18 October'."),
        (PHONE, "phone-number", "medium", "Raw phone number. Comes out as one huge number or too fast.",
         "Write it in groups of digits (Cartesia: <spell>), or send it by message."),
        (CODE, "code-read-aloud", "medium", "Order ID, reference or code in spoken text. Callers can't use it by ear.",
         "Drop it, or send it by message. If it must be said, spell it in short groups."),
    ]
    if policy == "written":
        return always + [
            (BIG_RAW_NUMBER, "ungrouped-number", "low", "Long number without grouping.",
             "Use Indian digit grouping (1,50,000) so the engine reads it as an amount."),
        ]
    sev = "medium" if policy == "words" else "low"
    hint = "Spell it out the way people say it" if policy == "words" else "Test how this engine reads it"
    return always + [
        (CURRENCY, "currency", sev, "Currency symbol or digit grouping.", f"{hint}: 'one thousand four hundred ninety-nine rupees'."),
        (SLASH_DATE, "date", sev, "Numeric date like 18/10. Ambiguous when read out.", f"{hint}: 'Saturday, the eighteenth of October'."),
        (TIME, "time", sev, "Clock-format time.", f"{hint}: 'half past five in the evening'."),
    ]


def check_spoken(report: Report, text: str, where: str, base_line: int | None, engine: dict):
    """Strict checks for text that goes straight to the voice engine."""
    def add(rule, sev, msg, fix, snippet):
        report.add(rule, sev, msg, fix, base_line, short(snippet), where)

    checks = [
        (MD_BULLET, "markdown", "high", "List or markdown in spoken text.", "Rewrite as one flowing sentence."),
        (MD_INLINE, "markdown", "high", "Markdown in spoken text.", "Remove the formatting; use word order for emphasis."),
        (EMOJI, "emoji", "high", "Emoji in spoken text. The engine skips it or reads its name.", "Delete it."),
        (URL, "url", "high", "A URL read aloud is useless on a call.", "Offer to send the link on WhatsApp or SMS."),
        (EMAIL, "email", "high", "An email address read aloud is hard to catch.", "Offer to send it by message."),
        *number_checks(engine["numbers"]),
        (UNIT, "unit", "low", "Abbreviated unit.", "Write the unit out: 'two kilos', 'five hundred grams'."),
        (ABBREV, "abbreviation", "low", "Abbreviation the engine may read literally.", "Write the full words."),
        (SYMBOL, "symbol", "low", "Symbol the engine reads as a word or skips.", "Replace with words: 'and', 'percent', 'or'."),
        (BRACKET, "brackets", "low", "Brackets don't exist in speech; the aside gets read flat or dropped.",
         "Make it its own short sentence or cut it."),
    ]
    for pattern, rule, sev, msg, fix in checks:
        m = pattern.search(text)
        if m:
            add(rule, sev, msg, fix, text if rule == "markdown" else m.group(0))

    if engine["native_script"]:
        roman = ROMAN_HINDI.findall(text)
        if len(roman) >= 3 and not DEVANAGARI.search(text):
            add("romanised-indic", "high",
                f"Romanised Hindi ({', '.join(sorted({r.lower() for r in roman})[:4])}…) going to {engine['label']}. "
                "Sarvam says romanised Indic input degrades pronunciation.",
                "Write Hindi in Devanagari and keep English words in English letters: 'आपका order confirm हो गया है।'",
                text)

    m = STIFF_HINDI.search(text)
    if m:
        add("stiff-hindi", "low", f"'{m.group(0)}' is formal IVR Hindi or a translated idiom; it sounds scripted on a call.",
            "Use everyday words: बताइए, भेज दूँ?, सही है?, and close with 'ठीक है जी, धन्यवाद।'.", text)
    m = WRITTEN_KANNADA.search(text)
    if m:
        add("written-kannada", "low", f"'{m.group(0)}' is written-register Kannada; it sounds like an announcement.",
            "Use polite spoken forms: call ಮಾಡ್ತೀನಿ, ಮಾತಾಡಬಹುದಾ?, ಇದ್ರೆ, ಆಗುತ್ತೆ.", text)

    for sentence in SENTENCE_SPLIT.split(text):
        n = len(words(sentence))
        if n > 25:
            add("long-sentence", "medium", f"Sentence of {n} words. Listeners lose the thread after about 20.",
                "Split it into two or three short sentences.", sentence)
    if text.count("?") > 1:
        add("stacked-questions", "medium", f"{text.count('?')} questions in one turn.", "Ask one question, then stop.", text)


def lint(prompt: str, welcome: str | None, known_vars: set[str] | None, tts: str = "generic",
         multilingual_enabled: bool | None = None) -> Report:
    engine = TTS_ENGINES.get(tts, TTS_ENGINES["generic"])
    report = Report()
    low = prompt.lower()
    report.stats.update(prompt_words=len(words(prompt)), tts=tts)

    # 1. Rules the prompt should contain.
    for rule, pattern, sev, msg, fix in PRESENCE_RULES:
        if not re.search(pattern, low):
            report.add(rule, sev, msg, fix)
    pattern, sev, msg, fix = NUMBER_RULE[engine["numbers"]]
    if not re.search(pattern, low):
        report.add("no-number-rule", sev, msg, fix)

    verbose = re.search(r"in (?:great |full )?detail|detailed|elaborate|comprehensive|thorough(?:ly)?|explain fully|everything about", low)
    if verbose:
        report.add("verbosity-trigger", "medium",
                   f"'{verbose.group(0)}' pushes the model toward long answers, which on a call become monologues.",
                   "Replace with: answer in a sentence or two, then ask if they want more.",
                   line_of(prompt, verbose.start()), short(prompt[verbose.start():verbose.start() + 60]))

    # 2. Languages and script.
    langs = [l for l in INDIAN_LANGUAGES if re.search(rf"\b{l}\b", low)]
    report.stats["indian_languages_mentioned"] = langs
    switching = re.search(r"switch|same language|language (?:the )?(?:user|caller|customer|they)|reply in|respond in|mirror", low)
    if len(langs) >= 2 and switching and not multilingual_enabled:
        report.add("multi-language-one-voice", "high",
                   f"Prompt expects {', '.join(langs)} callers, but one prompt drives one transcriber and voice language. "
                   "When the model switches language, the voice mispronounces it and speech-to-text mishears it.",
                   "On Bolna, turn on multilingual_config with a transcriber, synthesizer and prompt per language, and take "
                   "switching rules out of the prompt. Elsewhere, confirm the STT and TTS are multilingual before relying on a prompt rule.")
    elif switching and multilingual_enabled:
        report.add("switch-rule-with-multilingual", "medium",
                   "Prompt has language-switching instructions while multilingual_config is on. Bolna says to leave switching to the config.",
                   "Remove the switching instructions from the prompt.", line_of(prompt, switching.start()))
    if engine["native_script"] and langs and not re.search(
            r"devanagari|native script|kannada script|tamil script|telugu script|in (?:hindi|kannada|tamil|telugu) script|देवनागरी", low):
        report.add("no-script-rule", "medium",
                   f"{engine['label']} pronounces native script far better than romanised text, and nothing tells the model which to write.",
                   "Add: write Hindi in Devanagari (or Kannada in Kannada script); keep English words like order and payment in English letters; never translate them.")

    # 3. Risky content anywhere in the prompt that the model may copy into speech.
    for pattern, rule, msg, fix in [
        (URL, "url-in-prompt", "URLs in the prompt. The model will read them out when asked.",
         "Tell the model to offer sending links on WhatsApp or SMS, never to read them."),
        (EMAIL, "email-in-prompt", "Email addresses in the prompt.", "Tell the model to offer sending it by message."),
        (ISO_DATE, "machine-date-in-prompt", "Machine-format dates in the prompt.", "Write dates as speech."),
    ]:
        hits = list(pattern.finditer(prompt))
        if hits:
            examples = ", ".join(sorted({short(h.group(0), 30) for h in hits})[:4])
            report.add(rule, "medium", f"{msg} Found: {examples}", fix, line_of(prompt, hits[0].start()))
    if engine["numbers"] == "words" and report.has("no-number-rule"):
        hits = list(CURRENCY.finditer(prompt)) + list(TIME.finditer(prompt))
        if hits:
            examples = ", ".join(sorted({short(h.group(0), 30) for h in hits})[:4])
            report.add("numbers-in-prompt", "medium",
                       f"Prices or times in the prompt with no rule for saying them. Found: {examples}",
                       "Add the numbers rule, or write these in words in the prompt.", line_of(prompt, hits[0].start()))

    # 4. Lines the agent will likely say verbatim.
    for start, text in spoken_segments(prompt):
        check_spoken(report, text, "spoken-line", line_of(prompt, start), engine)

    # 5. Welcome message: spoken straight through TTS, first thing the caller hears.
    if welcome:
        check_spoken(report, welcome, "welcome", None, engine)
        n = len(words(welcome))
        secs = n / WORDS_PER_SECOND
        report.stats.update(welcome_words=n, welcome_seconds_est=round(secs, 1))
        if n > 30:
            report.add("long-welcome", "high" if n > 45 else "medium",
                       f"Welcome is {n} words, about {secs:.0f} seconds before the caller can speak.",
                       "Aim for under 25 words: who you are, why you're calling, one yes/no question.",
                       None, short(welcome), "welcome")
        if not re.search(r"\b(?:ai|a\.i\.|assistant|virtual|automated|bot)\b|सहायक|असिस्टेंट", welcome.lower()):
            report.add("no-ai-disclosure", "low",
                       "Welcome doesn't say it's an AI assistant. Callers who find out later trust it less.",
                       "Say it up front: 'I'm Asha, the AI assistant from <company>'.", None, short(welcome), "welcome")

    # 6. Dynamic variables.
    used = {a or b for a, b in VAR.findall(prompt + "\n" + (welcome or ""))}
    report.stats["variables_used"] = sorted(used)
    if known_vars is not None:
        for v in sorted(used - known_vars):
            report.add("undefined-variable", "high", f"{{{{{v}}}}} is used but not in the variables you pass per call.",
                       "Pass it on every call or remove it. Missing variables are read out literally or left blank.",
                       snippet=f"{{{{{v}}}}}")
    for v in sorted(used):
        if FORMATTED_VAR_HINT.search(v):
            report.add("format-variable", "low", f"{{{{{v}}}}} looks like a date, time, amount or number.",
                       "Pass it already formatted for speech ('Saturday, 18 October'), never as '2026-10-18T17:30:00Z'.",
                       snippet=f"{{{{{v}}}}}")

    if report.stats["prompt_words"] > 2500:
        report.add("long-prompt", "low", f"Prompt is {report.stats['prompt_words']} words. Rules buried deep get ignored more often.",
                   "Move reference facts to a knowledge base; keep persona, flow and rules in the prompt.")
    return report


# --- input helpers --------------------------------------------------------

PROMPT_KEYS = ("system_prompt", "systemPrompt", "prompt")
WELCOME_KEYS = ("agent_welcome_message", "welcome_message", "first_message", "firstMessage", "greeting")


def find_key(obj, keys):
    """Depth-first search for the first non-empty value under any of keys."""
    if isinstance(obj, dict):
        for k in keys:
            v = obj.get(k)
            if v not in (None, "", [], {}):
                return v
        for v in obj.values():
            r = find_key(v, keys)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, keys)
            if r is not None:
                return r
    return None


def tts_from_synthesizer(synth: dict | None) -> str:
    if not isinstance(synth, dict):
        return "generic"
    provider = str(synth.get("provider", "")).lower()
    model = str((synth.get("provider_config") or {}).get("model", "")).lower()
    if provider == "sarvam":
        return "sarvam-v4" if "v4" in model else "sarvam-v2" if "v2" in model else "sarvam-v3"
    if provider in ("cartesia", "elevenlabs"):
        return provider
    return "generic"


def read_text(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    if os.path.isfile(arg):
        with open(arg, encoding="utf-8") as fh:
            return fh.read()
    return arg


def render(report: Report) -> str:
    order = {"high": 0, "medium": 1, "low": 2}
    s = report.stats
    lines = [f"Speakability score: {report.score}/100  ({len(report.findings)} findings, voice: {TTS_ENGINES[s['tts']]['label']})"]
    if "welcome_words" in s:
        lines.append(f"Welcome: {s['welcome_words']} words, ~{s['welcome_seconds_est']}s")
    lines.append(f"Prompt: {s['prompt_words']} words; Indian languages named: {', '.join(s['indian_languages_mentioned']) or 'none'}")
    if s.get("variables_used"):
        lines.append("Variables: " + ", ".join("{{" + v + "}}" for v in s["variables_used"]))
    lines.append("")
    for f in sorted(report.findings, key=lambda f: (order[f.severity], f.line or 0)):
        loc = f"line {f.line}" if f.line else f.where
        lines.append(f"[{f.severity.upper():6}] {f.rule} ({loc})")
        lines.append(f"         {f.message}")
        if f.snippet:
            lines.append(f"         > {f.snippet}")
        lines.append(f"         fix: {f.fix}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="?", help="system prompt file, '-' for stdin, or literal text")
    ap.add_argument("--welcome", help="welcome message text or file")
    ap.add_argument("--agent-json", help="Bolna agent JSON; prompt, welcome and voice engine are read from it")
    ap.add_argument("--tts", choices=sorted(TTS_ENGINES), help="voice engine (default: from --agent-json, else generic)")
    ap.add_argument("--vars", help="comma-separated variables you pass per call; flags any others used")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    prompt = welcome = None
    tts, multilingual = "generic", None
    if args.agent_json:
        with open(args.agent_json, encoding="utf-8") as fh:
            data = json.load(fh)
        prompt = find_key(data, PROMPT_KEYS)
        welcome = find_key(data, WELCOME_KEYS)
        tts = tts_from_synthesizer(find_key(data, ("synthesizer",)))
        ml = find_key(data, ("multilingual_config",))
        multilingual = bool(isinstance(ml, dict) and ml.get("enabled"))
        if not isinstance(prompt, str):
            print("No system prompt found in the JSON.", file=sys.stderr)
            return 2
    if args.prompt:
        prompt = read_text(args.prompt)
    if args.welcome:
        welcome = read_text(args.welcome)
    if args.tts:
        tts = args.tts
    if prompt is None:
        ap.error("give a prompt file or --agent-json")

    known = {v.strip() for v in args.vars.split(",") if v.strip()} if args.vars else None
    report = lint(prompt, welcome if isinstance(welcome, str) else None, known, tts, multilingual)

    if args.json:
        print(json.dumps({"score": report.score, "stats": report.stats,
                          "findings": [asdict(f) for f in report.findings]}, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
