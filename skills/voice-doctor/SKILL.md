---
name: voice-doctor
description: Checkup and fixes for phone voice agents, built for Bolna with Sarvam, Deepgram, Cartesia, ElevenLabs, Plivo and Exotel, and usable on any voice stack. Rewrites system prompts and welcome messages so they sound right spoken (short turns, no markdown, numbers in the form the TTS wants, Hindi and Indic in native script), audits agent configs for latency, interruptions, endpointing, call cut-offs and language or voice mismatches, and reviews transcripts and latency_data across many calls. Use it whenever someone builds, tests, debugs or tunes a voice agent, AI calling agent or outbound calling bot, especially on Bolna, or shares a Bolna agent JSON, prompt, transcript or execution. Also use it for complaints like "sounds robotic", "long pause before it answers", "keeps cutting people off", "reads out asterisks or links", "mispronounces Hindi", "Hinglish", "calls end suddenly", or before launching a voice agent or calling batch.
---

# Voice Doctor

A checkup for voice agents. It finds what makes a call sound broken (unspeakable output, slow turns, the agent cutting people off, calls ending early, the wrong language or voice) and fixes it: a rewritten prompt and welcome message, a config change list, and a short script for a test call.

Three checks, used depending on what the user has:

| Check | Input | Script |
|---|---|---|
| Prompt | system prompt, welcome message, per-call variables | `scripts/lint_prompt.py` |
| Config | agent JSON | `scripts/audit_config.py` |
| Calls | executions or transcripts | `scripts/call_stats.py` |

A full checkup runs all three. Scripts are in this skill's `scripts/` folder, need only Python 3, and print plain text (add `--json` for structured output).

## 1. Gather

Work out what the user has before asking for anything. Ask only for what's missing and matters:
- **The agent**: agent JSON, an agent id, or the prompt and welcome message pasted in.
- **Per-call variables** they pass (e.g. `customer_name, order_id`), so missing ones can be caught.
- **Calls**, if any exist: executions or transcripts. These turn guesses into evidence.
- **Context** if it isn't obvious: who the callers are, which languages they speak, and how long a good call should take.

On Bolna, get data the way `references/bolna.md` ("Getting the data") describes: files first, then the Bolna MCP server or CLI if connected, then `scripts/bolna_api.py` (read-only, needs `BOLNA_API_KEY`). Never print or echo the API key. Save what you fetch to files so the scripts can read it:

```bash
python3 scripts/bolna_api.py agent <agent_id> > agent.json
python3 scripts/bolna_api.py executions <agent_id> --days 7 --max 50 > executions.json
```

## 2. Run the checks

```bash
python3 scripts/audit_config.py agent.json
python3 scripts/lint_prompt.py --agent-json agent.json --vars customer_name,order_id
python3 scripts/call_stats.py executions.json --agent-json agent.json
```

Without an agent JSON, lint a prompt file and name the voice engine, because number and script rules depend on it: `lint_prompt.py prompt.md --welcome welcome.txt --tts sarvam-v4` (engines: `sarvam-v4`, `sarvam-v3`, `sarvam-v2`, `cartesia`, `elevenlabs`, `generic`).

The scripts are a first pass. They match patterns; they can't judge whether the flow makes sense, the facts are right, the tone fits, or a domain risk is handled. So read the prompt and a few of the worst calls yourself (`call_stats.py` lists them) before diagnosing. When a script finding is wrong in context, drop it and say why in one line.

## 3. Diagnose

Rank findings by what the caller experiences, not by which check found them:
1. **Breaks the call**: calls cut off by the max duration, the wrong language or an unsupported voice, a voice id that doesn't exist for that model, missing variables read aloud, the agent reading out markdown, links or order IDs.
2. **Slow**: long gaps before the agent answers. Name the slowest component from `latency_data` and the configured waits.
3. **Talks over people or can't be interrupted**: endpointing, interruption words, turn length.
4. **Sounds robotic**: long turns, stacked questions, textbook Hindi, romanised Hindi going to a Sarvam voice, the wrong verb gender for the persona.
5. **Missing situations**: busy, wrong person, voicemail, "are you a robot?", wants a human, opt-out.

Sanity-check the data before building on it. Speaking time longer than the call, the same customer name and order on every call, or a field that never varies usually means a logging or batch problem. Say so as its own finding instead of drawing conclusions from it (`call_stats.py` flags impossible talk time).

Join symptoms across sources into one finding with one fix. For example, "the agent interrupts callers 3 times per call" in the calls, plus `endpointing: 100` in the config, plus callers reading out pincodes in transcripts, is a single finding: raise endpointing to 400–500 ms.

## 4. Fix

Read `references/voice-prompt-rules.md` before rewriting, and `references/providers.md` for the agent's voice engine. Read `references/bolna.md` for config fields and safe ranges.

- **Rewrite the system prompt.** Keep the user's business logic, facts, offers and flow; change how it's said and add what's missing (speaking rules, numbers rule for the engine, script rule, situations, ending). Don't invent policies or facts. Where the prompt needs something only the user knows (refund policy, callback hours), leave a visible `[TODO: …]`.
- **Keep the rewrite lean.** A prompt that grows from 200 to 1,800 words processes slower and its rules get diluted. Aim for under about 900 words: one line per situation, and no notes to the user inside the prompt (those go in the report). Group short `[TODO]`s at the end.
- **Confirm who's on the line before any details.** Order, appointment, payment or account details are said only after the caller confirms they're the customer. Wrong numbers, family members and voicemail hear only who's calling and why.
- **Give structured variables a spoken form.** Item lists, addresses and similar values must not be dropped raw into a scripted line, or the model reads "1. Cotton Kurta (Blue, L) - ₹999". Either pass a ready-made phrase (`items = "एक blue kurta और एक dupatta"`) or tell the model how to summarise it.
- **Rewrite the welcome message**: under about 25 words, who, from where, why, one yes/no question, says it's an AI assistant, no personal details yet.
- **List per-call variables** the new prompt uses, with a speakable example value for each (`delivery_date = "शनिवार, 18 अक्टूबर"` or `"Saturday, 18 October"`, never an ISO timestamp).
- **Config changes** as a table (field, now, suggested, why) plus a JSON snippet of just the changed fields in Bolna's structure. When switching the transcriber provider, carry `endpointing` over: Bolna applies it to every transcriber, and leaving it out falls back to a low default.
- **Indian languages**: for a Sarvam voice, write Hindi in Devanagari with English words left in Latin script, in everyday spoken style, and use the persona's verb gender consistently. For callers speaking different languages, fix it in config (Bolna `multilingual_config`), not with prompt rules.

Then measure the result instead of estimating it:
- Re-run `lint_prompt.py` on the rewritten prompt and welcome. Aim for 90 or above; explain any finding left on purpose.
- Put the config changes, rewritten prompt and welcome into `config-changes.json` (same structure as the agent; `null` removes a field) and run `python3 scripts/apply_changes.py agent.json config-changes.json -o agent.fixed.json`. It merges them without touching the original, prints the config and speakability scores before and after, flags any new finding the changes introduce, and marks each field PATCH or PUT. Quote those numbers in the report; don't hand-merge a scratch copy.

## 5. Deliver

Write the results into a `voice-doctor/` folder next to the user's files (or the project root), so they can diff and paste them:
- `report.md`: the checkup report (template below)
- `system_prompt.md` and `welcome.txt`: the rewrites
- `config-changes.json`: only the changed fields
- `agent.fixed.json`: the merged agent from `apply_changes.py`, ready to PUT after a backup

Report template:

```markdown
# Voice checkup: <agent name>

Speakability <before> → <after> · Config <before> → <expected after> · <N> calls reviewed
(Scores are heuristics from voice-doctor's checks, useful for tracking progress, not a quality guarantee.)

## Fix these first
1. <Problem as the caller hears it>: <evidence>. Fix: <change>. Expected effect: <what changes on the call>.
2. …

## Prompt
<What changed and why, briefly. Point to system_prompt.md and welcome.txt.>

## Config
| Field | Now | Suggested | Why |

## Calls
<Latency p50/p95 by component, interruptions, turn length, dead air, loops, cut-offs: only what the data shows.>

## Test call
<5–8 things to try on a real call that exercise the fixes, e.g. interrupt mid-sentence, read out a pincode slowly, answer in Kannada, say "I'm busy", stay silent for ten seconds, ask for the website.>

## Not checked
<What there was no data for, and assumptions made.>
```

Keep `report.md` under about 1,200 words: the top fixes with evidence, the config table, the test call, and what wasn't checked. Detail beyond that rarely gets read. Keep the chat reply under about 150 words: the top three fixes, the score change, and where the files are.

## Applying changes

voice-doctor reads; it doesn't change live agents on its own. If the user wants changes applied, show exactly what will change, get a clear yes, back up the current config, then apply with their tool of choice (dashboard, Bolna MCP `update_agent`, `bolna agents update`, or Bolna's `manage-agents` skill). `references/bolna.md` covers which fields PATCH can change and which need a full PUT.

## Other platforms

The prompt rules and the call review work on any stack (Vapi, Retell, LiveKit, Pipecat, custom). Map the config ideas to that platform's names: endpointing or end-of-turn silence, interruption threshold, maximum call length, voicemail detection, TTS buffering, streaming. `audit_config.py` only understands Bolna's schema, so for other platforms review the config by hand against `references/bolna.md`'s table and `references/providers.md`. `call_stats.py` works on any JSON with `transcript` strings in `assistant:`/`user:` lines; latency and interruption stats need Bolna's `latency_data`.

## Care points

- **Vendor docs conflict** in places (Sarvam number preprocessing, ElevenLabs normalisation defaults, Bolna default values). When a fix depends on one, say so and make it part of the test call instead of stating it as fact.
- **Don't promise latency numbers.** Say what should improve and how to check it in the next calls' `latency_data`.
- **Transcripts contain personal data** (names, phone numbers, addresses). Quote only what's needed as evidence, and mask it: "flat [n], [building], near …", "pincode [6 digits]", "+91 98xxx xxxxx". Don't reuse a caller's real pincode or address as an example in the rewritten prompt.
- **One bad call vs many**: for a deep dive into a single execution's raw logs, Bolna's own `debug-bolna-calls` skill is built for that; mention it if the user has Bolna's skills installed.
