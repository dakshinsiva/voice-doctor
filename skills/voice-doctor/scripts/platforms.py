"""Config checks for Vapi assistants and Retell agents.

Called by audit_config.py, which detects the platform and passes in an Audit to
fill. Field names, units and ranges come from each platform's OpenAPI spec,
checked 2026-10-26; sources are in references/vapi.md and references/retell.md.
"""

from __future__ import annotations

import json
import re

INDIC = {"hi", "kn", "ta", "te", "ml", "mr", "bn", "gu", "pa", "or", "od", "as", "ur"}
LANG_NAME = {"hindi": "hi", "kannada": "kn", "tamil": "ta", "telugu": "te", "malayalam": "ml", "marathi": "mr",
             "bengali": "bn", "bangla": "bn", "gujarati": "gu", "punjabi": "pa", "odia": "or", "urdu": "ur"}
TRANSFER_PROMISE = re.compile(r"transfer|connect (?:you|them|aapko|the \w+)\b|connect kar|human agent|customer care|representative")

# Vapi
VAPI_DEEPGRAM_INDIC = {"hi", "ta", "te", "kn", "mr", "bn", "ur"}  # no ml, gu, pa
VAPI_LEGACY = ["silenceTimeoutSeconds", "endCallFunctionEnabled", "backchannelingEnabled",
               "backgroundDenoisingEnabled", "forwardingPhoneNumber", "messagePlan"]
# Retell
RETELL_INDIC = {"hi", "kn", "mr", "ta", "ur"}  # plus en-IN; no te, ml, bn, gu, pa
RETELL_DEEPGRAM_INDIC = {"hi"}
ELEVEN_V25_INDIC = {"hi", "ta"}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def base(code) -> str:
    return str(code or "").lower().replace("_", "-").split("-")[0]


def prompt_languages(prompt: str) -> set[str]:
    low = (prompt or "").lower()
    return {code for name, code in LANG_NAME.items() if re.search(rf"\b{name}\b", low)}


def call_cap(a, field, seconds, exp, default_note=""):
    if seconds is not None and exp and exp * 60 > seconds:
        a.add("call-cut-off", "high", field, int(seconds), f"{int(exp * 60 + 60)} s or more",
              f"Calls are force-ended at {int(seconds)} s{default_note}, but this flow takes up to {exp:g} minutes.")


# --- Vapi --------------------------------------------------------------------

def audit_vapi(a, d: dict, prompt: str, exp: float | None) -> None:
    model = d.get("model") or {}
    tr = d.get("transcriber") or {}
    voice = d.get("voice") or {}
    ssp = d.get("startSpeakingPlan") or {}
    stop = d.get("stopSpeakingPlan") or {}
    tools = [t for t in model.get("tools") or [] if isinstance(t, dict)]
    tool_types = {t.get("type") for t in tools}
    tr_p, tr_lang = str(tr.get("provider", "")).lower(), base(tr.get("language"))
    v_p, v_model, v_lang = str(voice.get("provider", "")).lower(), str(voice.get("model", "")).lower(), base(voice.get("language"))
    a.summary.update(transcriber=f"{tr_p} {tr.get('model', '')} ({tr.get('language')})",
                     llm=f"{model.get('provider', '')} {model.get('model', '')}",
                     synthesizer=f"{v_p} {voice.get('model', '')} ({voice.get('language')})",
                     telephony="vapi", multilingual=tr_lang == "multi", platform="vapi")
    langs = prompt_languages(prompt)

    md = num(d.get("maxDurationSeconds"))
    call_cap(a, "maxDurationSeconds", md if md is not None else 600, exp, "" if md is not None else " (Vapi's default)")

    wait = num(ssp.get("waitSeconds"))
    if wait is not None and wait > 2:
        a.add("endpointing-too-high", "medium", "startSpeakingPlan.waitSeconds", wait, "0.4–1.5",
              f"The agent waits {wait:g} s after the caller stops before replying.")
    smart = str((ssp.get("smartEndpointingPlan") or {}).get("provider", "")).lower()
    if smart == "livekit" and tr_lang not in ("en", ""):
        a.add("smart-endpointing-language", "medium", "startSpeakingPlan.smartEndpointingPlan.provider", "livekit", "vapi",
              "Vapi recommends LiveKit endpointing for English only; use its own 'vapi' endpointing for other languages.")
    on_num = num((ssp.get("transcriptionEndpointingPlan") or {}).get("onNumberSeconds"))
    if on_num is not None and on_num < 0.5:
        a.add("number-endpointing-short", "low", "startSpeakingPlan.transcriptionEndpointingPlan.onNumberSeconds", on_num,
              "0.8–1.0", "Callers reading out phone numbers or pincodes pause between digits; a short wait cuts them off.")

    words = num(stop.get("numWords"))
    if words is None or words == 0:
        a.add("interrupt-too-easy", "medium", "stopSpeakingPlan.numWords", stop.get("numWords", "unset (0)"), "1–2",
              "At 0, any 0.2 s of sound stops the agent. Vapi suggests raising it so 'okay' or a cough doesn't interrupt.")
    elif words >= 5:
        a.add("interrupt-too-hard", "medium", "stopSpeakingPlan.numWords", int(words), "1–3",
              "Callers can't stop the agent once it starts talking.")

    hooks = [h for h in d.get("hooks") or [] if isinstance(h, dict) and h.get("on") == "customer.speech.timeout"]
    if not hooks:
        a.add("no-idle-hook", "low", "hooks[customer.speech.timeout]", None, "a hook that says one line, then ends",
              "Nothing happens when the caller goes quiet. Add a customer.speech.timeout hook: an 'are you there?' line, "
              "then an endCall tool action.")
    elif tr_lang in INDIC:
        said = json.dumps([h.get("do") for h in hooks], ensure_ascii=False)
        if not re.search(r"[ऀ-෿]", said) and re.search(r"\b(?:are you|still there|hello)\b", said, re.I):
            a.add("online-check-language", "medium", "hooks[customer.speech.timeout].do", "English line",
                  f"the same line in '{tr_lang}'", "The 'are you there?' line is English on an Indian-language call.")
    legacy = [k for k in VAPI_LEGACY if k in d] + (["model.systemPrompt"] if "systemPrompt" in model else [])
    if legacy:
        a.add("legacy-fields", "low", ", ".join(legacy), "present", "current equivalents",
              "Not in Vapi's current assistant schema (silence and idle handling moved to hooks, end-call and transfer to "
              "model.tools). They may be ignored; check on a test call.")

    vm = d.get("voicemailDetection")
    if vm in (None, "off"):
        a.add("voicemail-off", "medium", "voicemailDetection", vm or "off", "a provider plan, e.g. {provider: vapi}",
              "For outbound calls, voicemail gets the whole script. Detection is off by default.")
    effort = str(model.get("reasoningEffort") or "").lower()
    if effort in ("medium", "high", "xhigh"):
        a.add("llm-reasoning-effort", "high", "model.reasoningEffort", effort, "none or low",
              "Reasoning runs before the first word of every reply.")
    mt = num(model.get("maxTokens"))
    if mt is not None and mt > 400:
        a.add("llm-max-tokens-high", "medium", "model.maxTokens", int(mt), "150–250", "Allows very long replies.")
    chunk = voice.get("chunkPlan") or {}
    if chunk.get("enabled") is False:
        a.add("tts-not-streaming", "high", "voice.chunkPlan.enabled", False, "true",
              "Without chunking the voice waits for the whole reply before speaking.")
    elif num(chunk.get("minCharacters")) and num(chunk.get("minCharacters")) > 60:
        a.add("tts-buffer-large", "low", "voice.chunkPlan.minCharacters", int(num(chunk["minCharacters"])), "30 (default)",
              "The voice waits for more text before it starts speaking.")

    if tr_p == "deepgram" and tr_lang in INDIC - VAPI_DEEPGRAM_INDIC:
        a.add("stt-language-unsupported", "high", "transcriber.language", tr_lang, "azure or 11labs scribe",
              f"Deepgram on Vapi has no '{tr_lang}'.")
    lang = v_lang or tr_lang
    if v_p in ("11labs", "elevenlabs") and ("v2_5" in v_model or "flash" in v_model or "turbo" in v_model) \
            and lang in INDIC - ELEVEN_V25_INDIC:
        a.add("tts-language-unsupported", "high", "voice.model", v_model, "cartesia or the vapi voice",
              f"ElevenLabs Flash/Turbo v2.5 supports Hindi and Tamil only among Indian languages, not '{lang}'.")
    if len(langs) >= 2 and tr_lang != "multi":
        a.add("multilingual-off", "high", "transcriber.language", tr.get("language"), "multi (Deepgram nova-3)",
              f"The prompt expects {', '.join(sorted(langs))} callers, but the transcriber is fixed to one language.")

    outcomes = (d.get("artifactPlan") or {}).get("structuredOutputIds") or (d.get("artifactPlan") or {}).get("structuredOutputs")
    if not (d.get("server") or {}).get("url") and not outcomes:
        a.add("no-outcome-capture", "medium", "server.url / artifactPlan.structuredOutputs", None, "one of them",
              "Nothing records what happened on each call.")
    if "analysisPlan" in d:
        a.add("deprecated-analysis-plan", "low", "analysisPlan", "present", "artifactPlan.structuredOutputs",
              "Vapi has deprecated analysisPlan.")
    if TRANSFER_PROMISE.search((prompt or "").lower()) and "transferCall" not in tool_types:
        a.add("transfer-promise", "medium", "model.tools", sorted(t for t in tool_types if t), "a transferCall tool",
              "The prompt promises a transfer, but there's no transferCall tool.")
    if "endCall" not in tool_types and not d.get("endCallPhrases"):
        a.add("no-end-call", "low", "model.tools", sorted(t for t in tool_types if t), "an endCall tool",
              "The agent has no way to hang up when the conversation is done.")


# --- Retell ------------------------------------------------------------------

def audit_retell(a, agent: dict, llm: dict, prompt: str, exp: float | None) -> None:
    langs_cfg = agent.get("language")
    lang_list = [base(x) for x in (langs_cfg if isinstance(langs_cfg, list) else [langs_cfg]) if x]
    stt = agent.get("custom_stt_config") or {}
    stt_p = str(stt.get("provider", "")).lower()
    v_model = str(agent.get("voice_model") or "").lower()
    tools = [t for t in llm.get("general_tools") or [] if isinstance(t, dict)]
    tool_types = {t.get("type") for t in tools}
    mc = llm.get("model_config") or {}
    model = (mc.get("primary") or {}).get("model") or llm.get("model")
    a.summary.update(transcriber=f"{agent.get('stt_mode', 'fast')} {stt_p} ({langs_cfg})", llm=str(model),
                     synthesizer=f"{agent.get('voice_id')} {v_model}", telephony="retell",
                     multilingual=len(lang_list) > 1, platform="retell")
    prompt_langs = prompt_languages(prompt)

    md = num(agent.get("max_call_duration_ms"))
    call_cap(a, "agent.max_call_duration_ms", (md if md is not None else 3600000) / 1000, exp,
             "" if md is not None else " (Retell's default)")

    sil = num(agent.get("end_call_after_silence_ms"))
    if sil is None or sil > 60000:
        a.add("silence-hangup-long", "medium", "agent.end_call_after_silence_ms", agent.get("end_call_after_silence_ms", "unset (600000)"),
              "15000–30000", f"A silent call stays open for {int((sil or 600000) / 60000)} minutes and is billed.")
    rem, rem_n = num(agent.get("reminder_trigger_ms")), agent.get("reminder_max_count")
    if rem_n == 0:
        a.add("online-check-off", "low", "agent.reminder_max_count", 0, "1–2", "No 'are you there?' when the caller goes quiet.")
    elif sil is not None and sil <= (rem if rem is not None else 10000):
        a.add("silence-hangup-before-check", "high", "agent.end_call_after_silence_ms", int(sil),
              f"more than {int(rem or 10000)}", "The call ends before the reminder can play.")

    resp = num(agent.get("responsiveness"))
    if resp is not None and resp < 0.5:
        a.add("slow-responsiveness", "medium", "agent.responsiveness", resp, "0.8–1", "Low responsiveness adds a pause before every reply.")
    sens = num(agent.get("interruption_sensitivity"))
    if sens is not None and sens == 0:
        a.add("interrupt-too-hard", "high", "agent.interruption_sensitivity", 0, "0.8–0.9", "At 0 the caller can never interrupt.")
    elif sens is not None and sens < 0.4:
        a.add("interrupt-too-hard", "medium", "agent.interruption_sensitivity", sens, "0.8–0.9",
              "Callers struggle to stop the agent once it starts talking.")
    if agent.get("voicemail_option") in (None, {}):
        a.add("voicemail-off", "medium", "agent.voicemail_option", None, "{action: {type: hangup}} or a short static_text",
              "Agents created through the API get no voicemail detection unless this is set.")

    if any(l == "multi" for l in lang_list):
        a.add("language-multi-rejected", "high", "agent.language", langs_cfg, "a list of locales, e.g. [hi-IN, en-IN]",
              "Retell has rejected the scalar 'multi' since 31 July 2026.")
    want = {l for l in lang_list if l in INDIC} | (prompt_langs & INDIC)
    for l in sorted(want - RETELL_INDIC):
        a.add("platform-language-unsupported", "high", "agent.language", l, "a platform that supports it (e.g. Bolna + Sarvam)",
              f"Retell has no '{l}' locale (Indian locales: en-IN, hi-IN, kn-IN, mr-IN, ta-IN, ur-IN).")
    if stt_p == "deepgram":
        for l in sorted({l for l in lang_list if l in INDIC} - RETELL_DEEPGRAM_INDIC):
            a.add("stt-language-unsupported", "high", "agent.custom_stt_config.provider", "deepgram", "azure or soniox",
                  f"Deepgram on Retell covers only Hindi among Indian languages, not '{l}'.")
    if ("eleven_flash_v2_5" in v_model or "eleven_multilingual_v2" in v_model):
        for l in sorted({l for l in lang_list if l in INDIC} - ELEVEN_V25_INDIC):
            a.add("tts-language-unsupported", "high", "agent.voice_model", v_model, "eleven_v3",
                  f"{v_model} covers Hindi and Tamil only; '{l}' needs eleven_v3.")
    if len(prompt_langs) >= 2 and len(lang_list) < 2:
        a.add("multilingual-off", "high", "agent.language", langs_cfg, "a list of the callers' locales",
              f"The prompt expects {', '.join(sorted(prompt_langs))} callers, but the agent has one language.")

    if not mc and any(k in llm for k in ("model", "model_temperature", "s2s_model", "model_high_priority")):
        a.add("deprecated-model-fields", "low", "retell_llm.model", llm.get("model"), "model_config",
              "Retell deprecates the legacy model fields on 31 January 2027; move to model_config.")
    if llm.get("states"):
        a.add("multi-prompt-sunset", "low", "retell_llm.states", f"{len(llm['states'])} states", "single prompt or Conversation Flow",
              "Retell stops creating multi-prompt agents on 15 December 2026.")
    if not agent.get("webhook_url") and not agent.get("post_call_analysis_data"):
        a.add("no-outcome-capture", "medium", "agent.webhook_url / post_call_analysis_data", None, "one of them",
              "Nothing records what happened on each call.")
    if TRANSFER_PROMISE.search((prompt or "").lower()) and "transfer_call" not in tool_types:
        a.add("transfer-promise", "medium", "retell_llm.general_tools", sorted(t for t in tool_types if t), "a transfer_call tool",
              "The prompt promises a transfer, but there's no transfer_call tool.")
    if "end_call" not in tool_types:
        a.add("no-end-call", "low", "retell_llm.general_tools", sorted(t for t in tool_types if t), "an end_call tool",
              "The agent has no way to hang up when the conversation is done.")
    if llm.get("begin_message") is None and llm.get("start_speaker") == "agent":
        a.add("generated-greeting", "low", "retell_llm.begin_message", None, "a fixed first line",
              "The LLM writes the greeting on every call: slower and less predictable than a fixed line.")
