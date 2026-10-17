# Bolna reference

Verified against https://www.bolna.ai/docs, the OpenAPI spec and the open-source engine (github.com/bolna-ai/bolna) on 2026-10-17. Any docs page is available as Markdown by adding `.md` to its URL; the index is https://www.bolna.ai/docs/llms.txt. No live API calls were made while writing this, so confirm surprising values against `usage_breakdown` on a real execution, which echoes the settings a call actually ran with.

## Contents
- Getting the data
- Agent config map
- The settings that shape latency and turn-taking
- Execution payload and latency_data
- Applying changes
- Bolna's own skills, and where voice-doctor fits

## Getting the data

Use whichever the user already has, in this order:
1. **Files they give you**: an agent JSON export, a pasted prompt, transcripts.
2. **Bolna MCP server** (`https://mcp.bolna.ai/api/mcp`) or the Claude connector, if connected: `get_agent`, `list_agent_executions` (defaults to the last 7 days), `get_execution`, `get_execution_raw_logs`.
3. **Bolna CLI** (`bolna agents view <id> --json`, `bolna calls list --json`), if installed.
4. **This skill's script**: `scripts/bolna_api.py` (read-only GET calls; needs `BOLNA_API_KEY` in the environment or `./.env`; never print the key).

REST: base `https://api.bolna.ai`, header `Authorization: Bearer <key>`. Keys: platform.bolna.ai → Developers → API Keys (main account `bn-…`, sub-account `sa-…`). Rate limit 500/min on executions and agent GETs; 429 when exceeded.

## Agent config map

`GET /v2/agent/{agent_id}`. Body for create/update is `{agent_config, agent_prompts}`.

```
agent_prompts.task_1.system_prompt          # variables: {{name}} (single-brace {name} also accepted)
agent_config
  agent_name, agent_welcome_message, webhook_url, call_summary_enabled
  calling_guardrails {call_start_hour, call_end_hour}
  tasks[0]                                   # task_type: conversation (also extraction, summarization)
    toolchain {execution: parallel|sequential, pipelines: [["transcriber","llm","synthesizer"]]}
    tools_config
      llm_agent {agent_type: simple_llm_agent|knowledgebase_agent|graph_agent|realtime_agent,
                 agent_flow_type: "streaming",
                 llm_config {provider, model, max_tokens (100), temperature (0.1),
                             reasoning_effort, verbosity, ...}}
      transcriber {provider, model, language (ISO 639-1: "hi", not "hi-IN"), stream (true),
                   endpointing (ms), keywords (comma-separated), context, encoding,
                   sampling_rate, vad_threshold, ...}
      synthesizer {provider, provider_config {voice, voice_id, model, language, speed, ...},
                   stream (true), caching (true), buffer_size (250), audio_format}
      input / output {provider: plivo|exotel|vobiz|twilio|sip-trunk|..., format}
      api_tools, s2s, multilingual_config, web_search
    task_config {...}                        # see below
```

`multilingual_config`: `enabled`, `active_language`, `languages{code: {transcriber, synthesizer, system_prompt, handoff_message, agent_name}}`, `language_switch_trigger` (`requested_or_auto_detected` default, or `caller_requested`). Auto-detected languages: en, hi, ta, te, kn, ml, mr, bn, gu, pa, ur.

`synthesizer.provider_config.language` is required for cartesia, sarvam, smallest, rime, azuretts, gemini, soniox and polly.

## The settings that shape latency and turn-taking

API defaults first; the self-hosted engine has different defaults (see the end of this section).

| Field | Where | Default | What it does | Guidance |
|---|---|---|---|---|
| `endpointing` | transcriber | 500 (spec; some pages say 250) | Silence in ms before the caller's turn counts as finished | 200–300 typical (Bolna engine tab). Raise to 400–500 for callers who pause: older callers, people reading out numbers. Lower toward 100 only for fast scripted flows. It's a Bolna-side setting that applies whatever the transcriber, Sarvam included (Bolna's Sarvam page sets 500 in its example), so keep it when switching providers; leaving it out falls back to a low default. Deepgram Flux uses `eot_threshold`/`eot_timeout_ms` instead. |
| `incremental_delay` | task_config | 400 | "Linear Delay" in the UI: extra wait added before responding | 400–500 alongside endpointing 200–300. |
| `number_of_words_for_interruption` | task_config | 2 | Words the caller must say to interrupt the agent | 1 lets coughs and "hmm" cut the agent off on noisy lines; 4+ means callers can't stop a long turn. "Stop", "wait", "hold on" always interrupt. Turn on noise cancellation before lowering it. |
| `hangup_after_silence` | task_config | 10 s | Hang up after this much caller silence | 6–10 s. |
| `check_if_user_online` / `trigger_user_online_message_after` | task_config | true / 10 | "Are you there?" prompt after silence | 8–15 s. |
| `call_terminate` | task_config | 90 s (some Bolna pages say 300) | **Maximum call length** | Must exceed your longest real call. The 90 s default cuts off any flow longer than a quick confirmation. |
| `voicemail` (+ `voicemail_detection_duration` etc.) | task_config | false | Voicemail detection | Turn on for outbound. |
| `noise_cancellation_level` | task_config | null | Noise cancellation strength | Use on street and market calls before touching interruption settings. |
| `backchanneling` | task_config | false | "Hmm", "achha" while the caller talks | Test with real callers; easy to overdo. |
| `stream` | transcriber, synthesizer | true | Streaming | Never turn off. |
| `buffer_size` | synthesizer | 250 | Characters buffered before speaking | Bolna's latency guide says 100–150 is typical. |
| `max_tokens` | llm_config | 100 | Reply length cap | Short replies are a prompt job; a very low cap cuts sentences mid-way, a very high cap allows monologues. |
| `reasoning_effort` | llm_config | – | Reasoning before answering | `none` or `low` for live calls (Bolna OpenAI page). |
| `temperature` | llm_config | 0.1 | | GPT-5 family models on Bolna require exactly 1, otherwise the API returns 400. |
| `keywords` | transcriber | – | STT keyword biasing | 10–20 terms you've actually seen misheard (brand names, products, place names). `context` describes the call; it isn't instructions. |
| `hangup_after_LLMCall` / `call_cancellation_prompt` | task_config | false / – | After each reply, an LLM check decides whether the call is over | With no `call_cancellation_prompt`, Bolna's default (`CHECK_FOR_COMPLETION_PROMPT` in `bolna/prompts.py`, @4d6accb) counts "thank you", a caller who "seems satisfied", or a goal that "appears achieved even without explicit confirmation" as complete. Indian callers say "theek hai, thank you" mid-call, so write a prompt that ends the call only after the agent's closing line. |
| `calling_guardrails` | agent_config | – | Allowed calling hours for batches | Set them for any outbound use. |
| input/output `provider` | tools_config | – | Telephony | For Indian numbers use Plivo, Exotel or Vobiz. Bolna's Indian-server routing (lower latency) needs Plivo plus Azure OpenAI as the LLM; Twilio calls are processed on US servers, and bringing your own provider keys routes calls through US servers too (https://www.bolna.ai/docs/enterprise/indian-server-configuration.md). |

Fields the open-source engine reads but the hosted API docs don't list (unconfirmed whether the hosted API stores them): `optimize_latency`, `use_fillers`, `max_silence_repeats`, `discard_pre_welcome_utterance`, `language_detection_turns`, `end_call_tool_mode`. `interruption_backoff_period` has no effect (its read is commented out).

Self-hosted engine defaults differ: `hangup_after_silence` 20, `incremental_delay` 900, `number_of_words_for_interruption` 1, `buffer_size` 40, `stream` false. Read the applied values from `usage_breakdown` instead of assuming.

## Execution payload and latency_data

`GET /v2/agent/{agent_id}/executions` takes `from` and `to` (required, UTC ISO 8601, at most 7 days apart), `page_number`, `page_size` (max 50), `status`, `call_type`, `answered_by_voice_mail`, `batch_id`. Returns `{page_number, page_size, total, has_more, data[]}`. `GET /executions/{id}` returns one call; `/executions/{id}/log` returns raw component logs.

Useful fields per execution:
- `status`, `smart_status`, `conversation_duration` (`completed` doesn't mean answered: check `conversation_duration > 0`), `answered_by_voice_mail`, `error_message`.
- `transcript`: newline-separated `assistant:` / `user:` lines.
- `telephony_data`: `duration`, `hangup_by`, `hangup_reason`, `ring_duration`, `recording_url`, `call_type`.
- `total_cost` (cents) and `cost_breakdown`.
- `usage_breakdown`: provider/model per component and the applied `endpointing`, `incremental_delay`, `buffer_size`, `hangup_after_silence`, `check_if_user_online`, `trigger_user_online_message_after`, `voicemail_detection_enabled`.
- `extracted_data`, `summary`.
- `latency_data` (https://www.bolna.ai/docs/concepts/call-latencies.md):
  - `time_to_first_audio` (ms), `region`
  - `transcriber.turns[].turn_latency[].audio_to_text_latency`
  - `llm.turns[].time_to_first_token`, `time_to_last_token`
  - `synthesizer.turns[].time_to_first_token`, `time_to_last_token` (turn `-1` is probably the welcome message; not documented)
  - `interruption_stats`: `total_interruptions`, `user_interrupted_agent_count`, `agent_interrupted_user_count`, `user_speaking_ms`, `agent_speaking_ms`, `longest_agent_monologue_ms`, `talk_to_listen_ratio`, `barge_in_recovery_rate`

Bolna's documented thresholds: transcriber over 100 ms per sequence, LLM first token over 1000 ms, synthesizer first chunk over 500 ms are slow; target under 600 ms end to end.

## Applying changes

voice-doctor reads; it doesn't write to Bolna on its own. To apply fixes, show the user the exact changes, get a clear yes, then use whatever they have: the dashboard, the MCP `update_agent` tool, the CLI (`bolna agents update`), or Bolna's `manage-agents` skill. `PATCH /v2/agent/{id}` only updates `agent_name`, `agent_welcome_message`, `webhook_url`, `synthesizer`, `ingest_source_config`, `telephony_provider`, `calling_guardrails`, `call_summary_enabled` and `agent_prompts`; transcriber and `task_config` changes need a full `PUT`, which replaces the whole agent, so back up the current config first.

## Bolna's own skills, and where voice-doctor fits

Bolna ships 20 skills (`npx skills add bolna-ai/skills`, https://github.com/bolna-ai/skills), including `create-agent`, `prompt-writing`, `debug-bolna-calls` (a symptom-to-fix runbook for one execution's latency and logs) and `get-executions`. Use them for building agents and for one-off call debugging. voice-doctor does what they don't: scores a whole agent config, checks prompts for how they sound, and aggregates latency, interruptions and transcript problems across many calls into one ranked fix list. If the user has Bolna's skills installed, suggest `debug-bolna-calls` for drilling into a single bad call.
