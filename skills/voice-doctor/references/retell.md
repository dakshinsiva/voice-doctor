# Retell reference

Checked against Retell's OpenAPI spec (`https://docs.retellai.com/openapi.yaml`, revision 2026-10-25) and docs on 2026-10-26. A Retell voice agent is two objects: the agent (`GET /get-agent/{agent_id}`) and its Retell LLM (`GET /get-retell-llm/{llm_id}`). voice-doctor reads them combined in one file as `{"agent": {...}, "retell_llm": {...}}`; the LLM object alone also works for prompt checks.

Doc pages: agent API https://docs.retellai.com/api-references/get-agent · LLM API https://docs.retellai.com/api-references/get-retell-llm · languages https://docs.retellai.com/build/language-support · multilingual https://docs.retellai.com/agent/multilingual · voicemail https://docs.retellai.com/build/handle-voicemail · transcription mode https://docs.retellai.com/build/transcription-mode · background noise https://docs.retellai.com/build/handle-background-noise · deprecations https://docs.retellai.com/deprecation-notice/2027/01-31_legacy_model_fields

## Where things live

| Concept | Field | Units, default, notes |
|---|---|---|
| First message | `retell_llm.begin_message`, `retell_llm.start_speaker` (`user`/`agent`) | `begin_message: null` means the LLM writes the greeting each call; `""` waits for the user. `agent.begin_message_delay_ms` 0–5000. |
| Prompt | `retell_llm.general_prompt`, `retell_llm.states[].state_prompt` | Multi-prompt (states) creation ends 2026-12-15. |
| Model | `retell_llm.model_config` (`type: cascading`, `primary: {model, tier}`, `backup`, `temperature` 0–1, default 0) | Legacy `model`, `model_temperature`, `s2s_model`, `model_high_priority` are deprecated (removed 2027-01-31). No max-tokens or reasoning-effort field. |
| Voice | `agent.voice_id`, `agent.voice_model`, `voice_speed` (0.5–2), `voice_temperature` (0–2), `fallback_voice_ids[]` | |
| Language | `agent.language`: one locale or a list | The scalar `"multi"` has been rejected since 2026-07-31; use a list. |
| End of turn | `agent.responsiveness` (0–1, default 1), `enable_dynamic_responsiveness`, `stt_mode` (`fast` default, `accurate`, `custom`), `custom_stt_config {provider, endpointing_ms}` | Dashboard endpointing ranges: Deepgram and Azure 100–10000 ms (default 1000), Soniox 500–3000, AssemblyAI 100–3000. |
| Interruption | `agent.interruption_sensitivity` (0–1, default 1) | 0 means never interruptible. In noise, lower slightly (e.g. 0.9 → 0.8). |
| Backchannel | `enable_backchannel`, `backchannel_frequency` (0–1, default 0.8), `backchannel_words[]` | |
| Silence hang-up | `agent.end_call_after_silence_ms` | Min 10000, **default 600000 (10 minutes)**. |
| "Are you there?" | `agent.reminder_trigger_ms` (default 10000), `reminder_max_count` (default 1; 0 disables) | Must fire before the silence hang-up. |
| Max duration | `agent.max_call_duration_ms` | 60000–7200000, default 3600000. |
| Voicemail | `agent.voicemail_option {action: {type: prompt / static_text / hangup / bridge transfer}}` | **Agents created through the API get no voicemail detection unless this is set.** |
| Noise | `denoising_mode` (`noise-cancellation` default), `ambient_sound` | |
| Outcomes | `agent.webhook_url`, `webhook_events[]`, `post_call_analysis_data[]` | |
| Transfer / end call | `retell_llm.general_tools[{type: "transfer_call", ...}]`, `[{type: "end_call", ...}]` | |
| Keywords / pronunciation | `boosted_keywords[]`, `pronunciation_dictionary[{word, alphabet, phoneme}]` | |

## Indian languages on Retell

- **Locales**: only en-IN, hi-IN, kn-IN, mr-IN, ta-IN and ur-IN. **No te, ml, bn, gu or pa**, and no Sarvam. For those languages, use a platform that supports them, such as Bolna with Sarvam.
- **TTS**:
  - hi-IN works on every provider.
  - ta-IN works on all providers except Inworld.
  - kn-IN and mr-IN work on Cartesia, Fish, ElevenLabs and OpenAI.
  - ElevenLabs `eleven_flash_v2_5` and `eleven_multilingual_v2` cover hi and ta only; kn, mr and ur need `eleven_v3`.
- **STT**:
  - Deepgram covers only hi-IN (and en-IN) among these.
  - kn, mr, ta and ur go through Azure or Soniox.
- **Multilingual**: set `language` to a list. Deepgram and Soniox switch mid-call; Azure handles one language.
