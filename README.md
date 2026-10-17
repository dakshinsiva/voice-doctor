# voice-doctor

**A checkup for your voice agent.** A Claude Code skill that finds why your phone agent sounds robotic, pauses too long, cuts people off or drops calls, and fixes it.

Built for **Bolna** with **Sarvam, Deepgram, Cartesia, ElevenLabs, Plivo and Exotel**, Indian languages first. The prompt and transcript checks work on any voice stack.

```
> my bolna COD agent sounds robotic and customers hang up, here's the agent export

Speakability 27 → 99 · Config 32 → 98 expected · 6 calls reviewed

Fix these first
1. It reads out order IDs, links, the support email and **bold** markup:
   12 codes, 2 links and 1 email were spoken across 5 calls.
2. Romanised Hindi going to a Sarvam voice ("Aapka order confirm ho gaya hai").
   Sarvam pronounces Devanagari far better: "आपका order confirm हो गया है।"
   And "anushka" is a v2/v3 voice name that doesn't exist on bulbul:v4-flash.
3. 2 of 5 answered calls were cut off mid-sentence at 90 s (call_terminate),
   but the prompt says the call takes 2–3 minutes.
4. ~3 s of silence before each reply: LLM first token p50 1,480 ms with
   reasoning_effort "medium", plus 1,000 ms of configured waiting.
5. The agent cuts in while customers dictate their address: endpointing is 100 ms.
```
<sub>Output from the synthetic example in [`examples/cod-confirmation`](examples/cod-confirmation).</sub>

## What it checks

**Prompt**: does it work out loud?
- Markdown, emojis, links, emails and order IDs the agent will read aloud
- Numbers in the form *your* voice engine wants. Sarvam Bulbul v4 Flash and Cartesia read `₹1,499` well; ElevenLabs Flash needs it spelled out.
- Hindi and other Indian languages in native script for Sarvam voices, English words kept in English, everyday not textbook phrasing, verb gender that matches the persona
- Turn length, stacked questions, a welcome message that's too long or doesn't say it's an AI
- Missing paths for busy, wrong person, voicemail, "are you a robot?", opt-out
- Variables used in the prompt but never passed on the call

**Config** (Bolna agent JSON): is it set up to feel fast and fair?
- Endpointing, interruption words, silence hang-up, linear delay, TTS buffer size, max tokens, reasoning effort
- `call_terminate` shorter than the call the prompt describes (the default is 90 s)
- STT and voice that don't support the caller's language (ElevenLabs Flash has no Kannada, Nova-3 no Malayalam), voice ids from the wrong model version, deprecated and sunsetting models
- Voicemail detection, calling hours, multilingual setup, Indian telephony

**Calls** (Bolna executions): what actually happened?
- Latency p50/p95 per component from `latency_data`, against Bolna's thresholds
- Who interrupts whom, longest monologues, words per turn
- "Hello? Are you there?" moments, word-for-word loops, calls ending at the duration cap
- Markdown, links and codes the agent actually said, and the worst calls to listen to first

Then it writes the fixes: a rewritten `system_prompt.md` and `welcome.txt`, a `config-changes.json` with only the fields to change, a report ranked by what callers experience, and a test-call script to verify the fixes.

## Install

As a Claude Code plugin:

```bash
claude plugin marketplace add dakshinsiva/voice-doctor
```

```bash
claude plugin install voice-doctor@voice-doctor
```

Or copy the skill folder into your personal skills:

```bash
git clone https://github.com/dakshinsiva/voice-doctor && cp -r voice-doctor/skills/voice-doctor ~/.claude/skills/
```

Then just describe the problem in Claude Code; the skill activates on its own. For example:

- "Check my Bolna agent before I launch the batch tomorrow: agent.json"
- "There's a 2 second pause before my agent answers, what's slow?"
- "Go through last week's calls in calls.json and tell me what's breaking"
- "Make this prompt sound natural on a phone call, it's for a Sarvam Hindi voice"

## Getting your data from Bolna

Use whichever you have:
- **Export**: download the agent JSON from the dashboard and point Claude at it.
- **Bolna MCP server or Claude connector**: Claude reads agents and executions directly.
- **Bolna CLI**: `bolna agents view <id> --json`.
- **The bundled script** (read-only): `export BOLNA_API_KEY=...`, then Claude runs `scripts/bolna_api.py`.

voice-doctor only reads. It never changes your agent or places calls. When you want fixes applied, it shows the exact changes and applies them only after you say yes, using your dashboard, MCP or CLI.

## Works alongside Bolna's skills

[Bolna's official skills](https://github.com/bolna-ai/skills) help you create agents, place calls and debug a single execution (`debug-bolna-calls`). voice-doctor is the checkup layer on top: it scores the whole config, checks prompts for how they sound, and aggregates problems across many calls into one ranked fix list. Use both.

## Run the scripts yourself

No dependencies beyond Python 3.

```bash
python3 skills/voice-doctor/scripts/audit_config.py examples/cod-confirmation/agent.json
```

```bash
python3 skills/voice-doctor/scripts/lint_prompt.py --agent-json examples/cod-confirmation/agent.json --vars customer_name,order_id
```

```bash
python3 skills/voice-doctor/scripts/call_stats.py examples/cod-confirmation/executions.json --agent-json examples/cod-confirmation/agent.json
```

Tests:

```bash
python3 -m unittest discover tests
```

## How it was tested

- **Against plain Claude**: 3 realistic tasks (prompt rewrite, config audit, call review), each run with and without the skill and graded on 30 pass/fail checks. With the skill: 30/30. Without: 28/30. Without the skill, Claude left the AI disclosure out of the welcome and quoted a customer's full address in the report. It also told the user Deepgram Nova-3 is English-only on Bolna, which is wrong, and in one run missed that `anushka` isn't a Bulbul v4 Flash voice.
- **Language review**: the Hindi and Kannada output was checked against a rubric built from Sarvam's and Bolna's guidance and research on code-mixing. Mostly natural; the rules were tightened where it wasn't.
- **Triggering**: with the skill installed, Claude Code (Sonnet 4.6) loaded it on 10 of 10 voice-agent requests and on none of 10 near-misses (TTS scripting, webhook code, transcription, number buying).
- **Real agents**: the scripts were run on public Bolna agents from open-source repos (COD confirmation, loan collections, Bolna's own multilingual example).

Small samples, one model each: read these as signs, not benchmarks. Eval prompts are in [`evals/`](evals).

## How it knows

The rules come from Bolna's docs and open-source engine, and from the Sarvam, Cartesia, Deepgram and ElevenLabs docs, checked on 17 October 2026. Where vendor docs contradict each other (they do, on number handling), the skill says so and makes it part of the test call instead of guessing. Sources are linked in [`references/`](skills/voice-doctor/references). Scores are heuristics for tracking progress, not a quality guarantee.

The example agents and calls in `examples/` are synthetic: Bolna's field names, made-up values.

## Contributing

Most wanted:
- Config checks for other platforms (Vapi, Retell, LiveKit, Pipecat)
- More Indian-language rules (Tamil, Telugu, Bengali, Marathi phrasing and script quirks)
- Real-world cases where a rule is wrong. Open an issue with the (redacted) prompt or transcript.

Run `python3 -m unittest discover tests` before sending a PR, and add a test for any new check.

## License

MIT
