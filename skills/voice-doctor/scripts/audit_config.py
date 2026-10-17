#!/usr/bin/env python3
"""Audit a Bolna agent config for latency, turn-taking and language problems.

Reads an agent JSON (GET /v2/agent/{id}, a dashboard export, or a create
payload) and checks the transcriber, LLM, voice, task_config and guardrails
against Bolna's docs and the speech vendors' language support. Also runs the
prompt linter on the agent's prompt and welcome message.

Rules and sources are in references/bolna.md and references/providers.md.

Usage:
  audit_config.py agent.json [--expect-minutes N] [--json]

--expect-minutes: the longest a real call should last. If omitted, it is
guessed from phrases like "2-3 minutes" in the prompt or welcome message.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lint_prompt import (INDIAN_LANGUAGES, PROMPT_KEYS, SEVERITY_COST, WELCOME_KEYS,  # noqa: E402
                         find_key, lint, tts_from_synthesizer)

INDIC = {"hi", "kn", "ta", "te", "ml", "mr", "bn", "gu", "pa", "od", "or", "as", "ur"}
LANG_NAME = {"hindi": "hi", "kannada": "kn", "tamil": "ta", "telugu": "te", "malayalam": "ml", "marathi": "mr",
             "bengali": "bn", "bangla": "bn", "gujarati": "gu", "punjabi": "pa", "odia": "od", "urdu": "ur"}
DEEPGRAM_NOVA3_INDIC = {"hi", "bn", "ta", "te", "kn", "mr", "gu", "pa"}
ELEVEN_FLASH_INDIC = {"hi", "ta"}
SARVAM_V4F_MISSING = {"ml", "od", "or"}
SARVAM_V4F_NARROW = {"kn", "ta", "te"}
SYNTH_NEEDS_LANGUAGE = {"cartesia", "sarvam", "smallest", "rime", "azuretts", "gemini", "soniox", "polly"}
INDIAN_TELEPHONY = {"plivo", "exotel", "vobiz"}
HEAVY_MODELS = re.compile(r"^(?:gpt-5\.5|gpt-5\.4|gpt-4\.1|gpt-4o|claude-opus|claude-sonnet)(?!.*mini)")


@dataclass
class Finding:
    rule: str
    severity: str
    field: str
    current: object
    suggested: str
    why: str


@dataclass
class Audit:
    findings: list[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def add(self, rule, severity, field_, current, suggested, why):
        self.findings.append(Finding(rule, severity, field_, current, suggested, why))

    @property
    def score(self) -> int:
        return max(0, 100 - sum(SEVERITY_COST[f.severity] for f in self.findings))


def base_lang(code) -> str:
    return str(code or "").lower().replace("_", "-").split("-")[0]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def expected_minutes(*texts: str) -> float | None:
    """Longest call length the prompt promises, from phrases like 'the call takes 2-3 minutes'.

    Only durations tied to the call count, so 'arrive 10 minutes early' is ignored."""
    best = None
    pattern = re.compile(
        r"\b(?:call|takes?|lasts?|duration|only)\b[^\d.\n]{0,30}?"
        r"(\d+(?:\.\d+)?)(?:\s*(?:-|–|to)\s*(\d+(?:\.\d+)?))?\s*(?:min|minute)", re.I)
    for t in texts:
        for m in pattern.finditer(t or ""):
            best = max(best or 0, float(m.group(2) or m.group(1)))
    return best


def conversation_task(data) -> dict:
    tasks = find_key(data, ("tasks",)) or []
    for t in tasks:
        if isinstance(t, dict) and t.get("task_type", "conversation") == "conversation":
            return t
    return tasks[0] if tasks and isinstance(tasks[0], dict) else {}


def audit(data: dict, expect_min: float | None) -> Audit:
    a = Audit()
    task = conversation_task(data)
    tools = task.get("tools_config") or {}
    tc = task.get("task_config") or {}
    llm = tools.get("llm_agent") or {}
    llm_cfg = llm.get("llm_config") or llm
    tr = tools.get("transcriber") or {}
    sy = tools.get("synthesizer") or {}
    pc = sy.get("provider_config") or {}
    ml = tools.get("multilingual_config") or find_key(data, ("multilingual_config",)) or {}
    ml_on = bool(isinstance(ml, dict) and ml.get("enabled"))
    telephony = str((tools.get("input") or {}).get("provider") or (tools.get("output") or {}).get("provider") or "").lower()
    outbound = telephony not in ("", "default", "database")
    prompt = find_key(data, PROMPT_KEYS)
    prompt = prompt if isinstance(prompt, str) else ""
    welcome = find_key(data, WELCOME_KEYS)
    welcome = welcome if isinstance(welcome, str) else ""
    low_prompt = prompt.lower()
    prompt_langs = {LANG_NAME[l] for l in INDIAN_LANGUAGES if l in LANG_NAME and re.search(rf"\b{l}\b", low_prompt)}

    tr_p, tr_m, tr_lang = str(tr.get("provider", "")).lower(), str(tr.get("model", "")).lower(), base_lang(tr.get("language"))
    sy_p, sy_m = str(sy.get("provider", "")).lower(), str(pc.get("model", "")).lower()
    sy_lang = base_lang(pc.get("language"))
    model = str(llm_cfg.get("model", "")).lower()
    a.summary = {"transcriber": f"{tr_p} {tr_m} ({tr.get('language')})", "llm": model,
                 "synthesizer": f"{sy_p} {sy_m} ({pc.get('language')})", "telephony": telephony or "unknown",
                 "multilingual": ml_on}

    # --- transcriber ---
    if tr and not tr.get("model"):
        a.add("stt-model-missing", "medium", "transcriber.model", None, "e.g. saaras:v4 or nova-3",
              f"No model set for {tr_p or 'the transcriber'}, so you get whatever the provider default is.")
    if tr.get("stream") is False:
        a.add("stt-not-streaming", "high", "transcriber.stream", False, "true",
              "Without streaming the agent waits for the whole utterance before transcribing. Bolna says never turn it off.")
    if "-" in str(tr.get("language", "")):
        a.add("stt-language-format", "medium", "transcriber.language", tr.get("language"), tr_lang,
              "Bolna's transcriber expects ISO 639-1 codes like 'hi'; 'hi-IN' is rejected.")
    if tr_p == "deepgram":
        if tr_m.startswith("nova-3") and tr_lang in INDIC - DEEPGRAM_NOVA3_INDIC:
            a.add("stt-language-unsupported", "high", "transcriber.model", f"{tr_m} / {tr_lang}", "sarvam saaras:v4",
                  f"Deepgram Nova-3 doesn't support '{tr_lang}'.")
        elif tr_lang == "multi" and prompt_langs - {"hi"}:
            a.add("stt-multi-hindi-only", "high", "transcriber.language", "multi", "sarvam saaras:v4 per language",
                  "Deepgram's multi mode covers Hindi as its only Indian language.")
        elif tr_m.startswith("nova-2") and tr_lang in INDIC:
            a.add("stt-old-model", "medium", "transcriber.model", tr_m, "nova-3 or sarvam saaras:v4",
                  "Nova-2 is the older generation; Nova-3 and Sarvam do better on Indian languages.")
        elif tr_lang in INDIC - {"hi"}:
            a.add("stt-consider-sarvam", "low", "transcriber.provider", "deepgram", "A/B test sarvam saaras:v4",
                  f"Deepgram supports '{tr_lang}', but Sarvam is built for Indian phone audio. Compare on real calls.")
    if tr_p == "sarvam" and tr_m in ("saarika:v2.5", "saaras:v2.5"):
        a.add("stt-deprecated", "medium", "transcriber.model", tr_m, "saaras:v4", "Sarvam has deprecated this model.")
    if tr_p == "sarvam" and tr.get("keywords") and tr_m != "saaras:v4":
        a.add("stt-keywords-ignored", "low", "transcriber.model", tr_m, "saaras:v4",
              "Sarvam keyterm biasing only works on saaras:v4.")
    ep = num(tr.get("endpointing"))
    if ep is None and not tr_m.startswith("flux"):
        a.add("endpointing-unset", "low", "transcriber.endpointing", None, "250 (400–500 if callers pause)",
              "Not set, so Bolna's default applies (its docs say anything from 150 to 500 ms). It applies to every "
              "transcriber, Sarvam included, so set it explicitly.")
    if ep is not None and not tr_m.startswith("flux"):
        if ep < 150:
            a.add("endpointing-too-low", "high", "transcriber.endpointing", int(ep), "250 (400–500 if callers pause)",
                  f"{int(ep)} ms of silence ends the caller's turn, so the agent cuts in when people pause mid-sentence or while reading out numbers.")
        elif ep > 700:
            a.add("endpointing-too-high", "medium", "transcriber.endpointing", int(ep), "250–500",
                  f"Every turn waits {int(ep)} ms of silence before the agent even starts thinking.")
    if not tr.get("keywords"):
        a.add("no-stt-keywords", "low", "transcriber.keywords", "", "10–20 terms",
              "Add brand, product and place names you've seen misheard. Bolna recommends 10–20 real misheard terms.")

    # --- voice ---
    if sy and not (pc.get("voice") or pc.get("voice_id")):
        a.add("tts-voice-missing", "high", "synthesizer.provider_config.voice", sy.get("voice"), "a voice id from the provider",
              "No voice id in provider_config. Labels like 'Indian Female' aren't voice ids; the call fails or falls back to a default voice.")
    if sy.get("stream") is False:
        a.add("tts-not-streaming", "high", "synthesizer.stream", False, "true", "Audio waits for the whole reply.")
    bs = num(sy.get("buffer_size"))
    if bs is not None and bs > 150:
        a.add("tts-buffer-large", "medium" if bs > 250 else "low", "synthesizer.buffer_size", int(bs), "100–150",
              f"The voice waits for {int(bs)} characters before speaking. Bolna's latency guide puts typical values at 100–150.")
    if sy_p in SYNTH_NEEDS_LANGUAGE and not pc.get("language"):
        a.add("tts-language-missing", "high", "synthesizer.provider_config.language", None, tr_lang or "hi",
              f"Bolna requires a language for {sy_p} voices.")
    if sy_lang and tr_lang and tr_lang != "multi" and sy_lang != tr_lang and not ml_on:
        a.add("stt-tts-language-mismatch", "medium", "synthesizer.provider_config.language", pc.get("language"), tr_lang,
              f"The transcriber listens for '{tr_lang}' but the voice speaks '{sy_lang}'.")
    voice_ids = [str(v) for v in (pc.get("voice_id"), pc.get("voice")) if v]
    if sy_p == "sarvam":
        if "v4" in sy_m:
            if sy_lang in SARVAM_V4F_MISSING:
                a.add("tts-language-unsupported", "high", "synthesizer.provider_config.model", sy_m, "bulbul:v3",
                      f"Bulbul v4 Flash has no '{sy_lang}' voices yet; Sarvam says keep that traffic on v3.")
            elif sy_lang in SARVAM_V4F_NARROW:
                a.add("tts-narrow-voices", "low", "synthesizer.provider_config.voice", voice_ids[0] if voice_ids else None,
                      "audition voices", f"Sarvam calls the v4 Flash '{sy_lang}' voice roster narrow; listen before choosing.")
            if voice_ids and not any(v.count("_") >= 2 for v in voice_ids):
                a.add("tts-voice-version", "high", "synthesizer.provider_config.voice", voice_ids[0], "e.g. ritu_hi_customer",
                      "Bulbul v4 Flash voices are named <name>_<lang>_<style>. v2/v3 names like 'anushka' or 'shubh' don't work on v4 Flash.")
        elif "v2" in sy_m:
            a.add("tts-legacy", "low", "synthesizer.provider_config.model", sy_m, "bulbul:v4-flash",
                  "Bulbul v2 is legacy. v4 Flash reads written numbers and code-mixed text better.")
    if sy_p == "cartesia":
        if "2025-10-27" in sy_m or sy_m.endswith(("latest", "preview")):
            a.add("tts-sunset", "high", "synthesizer.provider_config.model", sy_m, "sonic-3.6",
                  "This Cartesia snapshot or alias is deprecated; the 2025-10-27 snapshot sunsets on 20 October 2026.")
        elif sy_m == "sonic-3":
            a.add("tts-upgrade", "medium", "synthesizer.provider_config.model", sy_m, "sonic-3.6",
                  "Cartesia recommends sonic-3.6, and an older sonic-3 snapshot sunsets on 20 October 2026. Switch and re-test.")
    if sy_p == "elevenlabs":
        if "turbo" in sy_m:
            a.add("tts-deprecated", "low", "synthesizer.provider_config.model", sy_m, "eleven_flash_v2_5",
                  "ElevenLabs deprecated Turbo v2.5 in favour of Flash.")
        lang = sy_lang or tr_lang
        if lang in INDIC - ELEVEN_FLASH_INDIC and ("v2_5" in sy_m or "flash" in sy_m or not sy_m):
            a.add("tts-language-unsupported", "high", "synthesizer.provider_config.model", sy_m or "elevenlabs",
                  "sarvam bulbul:v4-flash (or eleven_v4_turbo)",
                  f"ElevenLabs Flash and Turbo v2.5 support Hindi and Tamil only among Indian languages, not '{lang}'. "
                  "eleven_v4_turbo covers far more languages; Sarvam is built for Indian ones.")
    if sy_p == "deepgram" and (sy_lang or tr_lang) in INDIC:
        a.add("tts-check-language", "medium", "synthesizer.provider", "deepgram", "sarvam bulbul:v4-flash",
              "Check Aura-2 supports this Indian language before using it; Sarvam is built for it.")

    # --- LLM ---
    if llm.get("agent_flow_type") and llm.get("agent_flow_type") != "streaming":
        a.add("llm-not-streaming", "high", "llm_agent.agent_flow_type", llm.get("agent_flow_type"), "streaming",
              "Non-streaming LLM output delays the first word until the whole reply is done.")
    effort = str(llm_cfg.get("reasoning_effort") or "").lower()
    if effort in ("medium", "high", "xhigh"):
        a.add("llm-reasoning-effort", "high", "llm_config.reasoning_effort", effort, "none or low",
              "Reasoning runs before the first word. Bolna recommends none or low for live calls.")
    temp = num(llm_cfg.get("temperature"))
    if model.startswith("gpt-5") and temp is not None and temp != 1:
        a.add("llm-temperature-gpt5", "high", "llm_config.temperature", llm_cfg.get("temperature"), "1",
              "Bolna rejects GPT-5 family models with any temperature other than 1 (HTTP 400).")
    mt = num(llm_cfg.get("max_tokens"))
    if mt is not None and mt > 250:
        a.add("llm-max-tokens-high", "medium", "llm_config.max_tokens", int(mt), "100–150",
              f"A {int(mt)}-token cap allows replies of 30+ seconds. Keep turns short in the prompt and cap them here.")
    elif mt is not None and mt < 40:
        a.add("llm-max-tokens-low", "medium", "llm_config.max_tokens", int(mt), "80–150",
              "Replies get cut off mid-sentence.")
    if str(llm_cfg.get("verbosity") or "").lower() in ("medium", "high"):
        a.add("llm-verbosity", "low", "llm_config.verbosity", llm_cfg.get("verbosity"), "low", "Voice needs short replies.")
    if HEAVY_MODELS.match(model):
        a.add("llm-heavy-model", "low", "llm_config.model", model, "try gpt-5.4-mini or gpt-4.1-mini",
              "Larger models usually have a slower first token. Compare time_to_first_token in latency_data before deciding.")
    if llm.get("agent_type") == "knowledgebase_agent":
        a.add("llm-rag", "low", "llm_agent.agent_type", "knowledgebase_agent", "check latency_data.rag",
              "A knowledge-base lookup runs each turn; check it isn't the slow step.")

    # --- task_config ---
    ct = num(tc.get("call_terminate"))
    exp = expect_min or expected_minutes(prompt, welcome)
    a.summary["expected_minutes"] = exp
    if ct is not None and exp and exp * 60 > ct:
        a.add("call-cut-off", "high", "task_config.call_terminate", int(ct), str(int(exp * 60 + 60)),
              f"Calls are force-ended at {int(ct)} s, but this flow takes up to {exp:g} minutes. Callers get cut off mid-call.")
    elif ct is not None and ct <= 120:
        a.add("call-terminate-short", "low", "task_config.call_terminate", int(ct), "your longest real call + 60 s",
              f"Maximum call length is {int(ct)} s (Bolna's default is 90). Check it covers your longest real call.")
    hs = num(tc.get("hangup_after_silence"))
    if hs is not None and hs > 20:
        a.add("silence-hangup-long", "low", "task_config.hangup_after_silence", int(hs), "6–10",
              f"Dead lines stay open for {int(hs)} s and get billed.")
    elif hs is not None and hs < 5:
        a.add("silence-hangup-short", "medium", "task_config.hangup_after_silence", int(hs), "6–10",
              "Callers who stop to think or fetch something get hung up on.")
    nw = num(tc.get("number_of_words_for_interruption"))
    if nw is not None and nw <= 1 and not tc.get("noise_cancellation_level"):
        a.add("interrupt-too-easy", "medium", "task_config.number_of_words_for_interruption", int(nw), "2",
              "One word (a cough, 'hmm', street noise) stops the agent mid-sentence. Bolna suggests noise cancellation before lowering this.")
    elif nw is not None and nw >= 5:
        a.add("interrupt-too-hard", "medium", "task_config.number_of_words_for_interruption", int(nw), "2–3",
              "Callers can't stop the agent once it starts talking.")
    idl = num(tc.get("incremental_delay"))
    if idl is not None and idl > 600:
        a.add("delay-high", "medium", "task_config.incremental_delay", int(idl), "400–500",
              f"Adds up to {int(idl)} ms of waiting before each reply.")
    if ep is not None and idl is not None and ep + idl > 1500:
        a.add("turn-wait-high", "medium", "transcriber.endpointing + task_config.incremental_delay",
              int(ep + idl), "under 1000", f"About {int(ep + idl)} ms of configured waiting before each reply, before any processing.")
    if outbound and not tc.get("voicemail"):
        a.add("voicemail-off", "medium", "task_config.voicemail", tc.get("voicemail", False), "true",
              "Outbound calls that hit voicemail get the whole script, and you pay for it.")
    trig = num(tc.get("trigger_user_online_message_after"))
    if tc.get("check_if_user_online") is not False and hs is not None and trig is not None and hs < trig:
        a.add("silence-hangup-before-check", "medium", "task_config.hangup_after_silence", int(hs), f"at least {int(trig)}",
              f"The call may hang up after {int(hs)} s of silence, before the 'are you there?' check at {int(trig)} s plays. "
              "Bolna doesn't document whether the timers overlap; confirm on a silent test call.")
    msg = tc.get("check_user_online_message")
    texts = list(msg.values()) if isinstance(msg, dict) else [msg] if isinstance(msg, str) else []
    if tr_lang in INDIC and texts and not any(re.search(r"[\u0900-\u0DFF]", t or "") for t in texts):
        a.add("online-check-language", "medium", "task_config.check_user_online_message", texts[0],
              f"the same line in the caller's language ({tr_lang})",
              "The 'are you still there?' line is in English on an Indian-language call; the caller hears a sudden switch.")
    if tc.get("check_if_user_online") is False:
        a.add("online-check-off", "low", "task_config.check_if_user_online", False, "true, after 8–15 s",
              "No 'are you there?' after silence; the call just goes quiet.")

    # --- agent level ---
    tasks = find_key(data, ("tasks",)) or []
    has_extraction = any(isinstance(t, dict) and t.get("task_type") in ("extraction", "summarization") for t in tasks)
    if not (find_key(data, ("webhook_url",)) or has_extraction or find_key(data, ("call_summary_enabled",))):
        a.add("no-outcome-capture", "medium", "agent_config.webhook_url / extraction task", None,
              "webhook_url, an extraction task, or call_summary_enabled",
              "Nothing records what happened on each call. Confirmations, cancellations and callback promises "
              "only exist in transcripts.")
    hook = find_key(data, ("webhook_url",))
    if isinstance(hook, str) and re.search(r"your[-_]?domain|example\.(?:com|org)|localhost|127\.0\.0\.1|placeholder|<", hook, re.I):
        a.add("webhook-placeholder", "medium", "agent_config.webhook_url", hook, "your live endpoint",
              "The webhook still points at a template or local address, so call outcomes never reach your system.")
    if re.search(r"transfer|connect (?:you|aapko)|connect kar|human agent|customer care agent se|representative", low_prompt) \
            and "transfer" not in json.dumps(tools).lower():
        a.add("transfer-promise", "medium", "tools_config.api_tools", None, "a transfer tool, or promise a callback instead",
              "The prompt promises to connect the caller to a person, but no call transfer is configured, so they wait "
              "on a silent line. Ignore this if transfer is set up outside this agent.")
    guard = find_key(data, ("calling_guardrails",))
    if outbound and not guard:
        a.add("no-calling-hours", "medium", "agent_config.calling_guardrails", None, "e.g. 9 to 20",
              "Without calling hours, batches and retries can ring people early morning or late night.")
    if len(prompt_langs) >= 2 and not ml_on:
        a.add("multilingual-off", "high", "tools_config.multilingual_config", "off", "enabled, one entry per language",
              f"The prompt expects {', '.join(sorted(prompt_langs))} callers, but the transcriber and voice are fixed to "
              f"'{tr_lang or sy_lang}'. Speech in the other language is misheard and replies are mispronounced.")
    if telephony == "twilio" and (tr_lang in INDIC or sy_lang in INDIC):
        a.add("telephony-india", "low", "tools_config.input.provider", "twilio", "plivo, exotel or vobiz",
              "Bolna processes Twilio calls on US servers. Its Indian-server routing needs Plivo with Azure OpenAI "
              "as the LLM, and your own provider keys also route through the US.")

    # --- prompt speakability (details: lint_prompt.py) ---
    if prompt:
        r = lint(prompt, welcome or None, None, tts_from_synthesizer(sy), ml_on)
        a.summary["speakability_score"] = r.score
        a.summary["speakability_findings"] = len(r.findings)
        a.summary["top_prompt_issues"] = [f.rule for f in sorted(
            r.findings, key=lambda f: {"high": 0, "medium": 1, "low": 2}[f.severity])][:6]
    return a


def render(a: Audit) -> str:
    order = {"high": 0, "medium": 1, "low": 2}
    s = a.summary
    out = [f"Config score: {a.score}/100  ({len(a.findings)} findings)",
           f"Stack: STT {s['transcriber']} | LLM {s['llm']} | TTS {s['synthesizer']} | telephony {s['telephony']}"
           f" | multilingual {'on' if s['multilingual'] else 'off'}"]
    if "speakability_score" in s:
        out.append(f"Prompt speakability: {s['speakability_score']}/100 ({s['speakability_findings']} findings; "
                   f"run lint_prompt.py --agent-json for details). Top: {', '.join(s['top_prompt_issues'])}")
    out.append("")
    for f in sorted(a.findings, key=lambda f: order[f.severity]):
        out.append(f"[{f.severity.upper():6}] {f.rule}: {f.field}")
        out.append(f"         now: {f.current!r}  ->  suggested: {f.suggested}")
        out.append(f"         {f.why}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("agent_json")
    ap.add_argument("--expect-minutes", type=float)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    with open(args.agent_json, encoding="utf-8") as fh:
        data = json.load(fh)
    result = audit(data, args.expect_minutes)
    if args.json:
        print(json.dumps({"score": result.score, "summary": result.summary,
                          "findings": [asdict(f) for f in result.findings]}, ensure_ascii=False, indent=2, default=str))
    else:
        print(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
