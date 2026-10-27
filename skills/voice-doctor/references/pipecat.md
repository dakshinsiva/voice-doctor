# Pipecat reference

Checked against pipecat-ai v1.14.0 source (released 2026-10-23) and docs.pipecat.ai on 2026-10-27. `audit_config.py` reads Pipecat bots straight from Python source; nothing is imported or run.

Source: https://github.com/pipecat-ai/pipecat/tree/v1.14.0 · changelog `CHANGELOG.md` · turn strategies `src/pipecat/turns/` · VAD `src/pipecat/audio/vad/vad_analyzer.py` · user aggregator `src/pipecat/processors/aggregators/llm_response_universal.py` · Smart Turn https://docs.pipecat.ai/api-reference/server/utilities/turn-detection/smart-turn-overview.md

**API changes to know:**
- 1.0.0 (2026-04-14) removed `PipelineParams(allow_interruptions)`, `interruption_strategies`, `MinWordsInterruptionStrategy`, `UserIdleProcessor` and `OpenAILLMContext`. `PipelineParams` is a pydantic model, so **old interruption settings are silently ignored**, not rejected.
- 0.0.105 deprecated `model=`, `voice_id=`, `params=InputParams(...)` and `live_options=LiveOptions(...)` on services in favour of `settings=Service.Settings(...)`.
- 1.3.0 renamed `PipelineTask` to `PipelineWorker` (the old name is an alias).

| Concept | Where | Default, units, guidance |
|---|---|---|
| VAD | `SileroVADAnalyzer(params=VADParams(confidence=0.7, start_secs=0.2, stop_secs=0.2, min_volume=0.6))`, passed via `LLMUserAggregatorParams(vad_analyzer=...)` | With Smart Turn, keep `stop_secs` at 0.2; Pipecat logs a warning otherwise. Every extra 0.1 s is added silence per turn. |
| Turn ending | default `UserTurnStrategies(stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())])`; alternative `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)` | Smart Turn v3 supports 23 languages, **including Hindi**. |
| Interruptions | `enable_interruptions=True` on each start strategy (`VADUserTurnStartStrategy`, `TranscriptionUserTurnStartStrategy`); `MinWordsUserTurnStartStrategy(min_words=)` | `enable_interruptions=False` means callers can't stop the bot. |
| Caller goes quiet | `LLMUserAggregatorParams(user_idle_timeout=0)` (0 = off) plus the `on_user_turn_idle` event | Set 8–15 s and say one line. |
| Hung calls | `PipelineWorker(idle_timeout_secs=300, cancel_on_idle_timeout=True)` | `None` means a hung call is never cancelled. |
| Max call length | `FastAPIWebsocketParams(session_timeout=None)` (seconds) + `on_session_timeout` | No cap by default. |
| Noise cancellation | `TransportParams(audio_in_filter=KrispVivaFilter() / AICFilter() / RNNoiseFilter())` | Default none. |
| LLM | `OpenAILLMService(settings=OpenAILLMService.Settings(model, system_instruction, temperature, max_completion_tokens, extra={}))` | No `reasoning_effort` field; it goes in `extra={"reasoning_effort": ...}` (from source; not documented for OpenAI). |
| Sarvam | `SarvamSTTService(settings=SarvamSTTService.Settings(model="saaras:v4", language=None))`; `SarvamTTSService(settings=SarvamTTSService.Settings(model="bulbul:v3", voice="shubh", language="en-IN", pace=1.0))` | **The voice defaults to English (en-IN)**: set `language=Language.HI_IN` for Hindi. |
| Others | `DeepgramSTTService.Settings(model="nova-3-general", language=Language.EN, endpointing=None)`; `ElevenLabsTTSService.Settings(model="eleven_flash_v2_5", language=None)`; `CartesiaTTSService.Settings(model="sonic-3.6", language=Language.EN)` | |
| Prompt and greeting | `Settings(system_instruction=...)` or `LLMContext(messages=[{"role": "system", ...}])`; greeting queued in `on_client_connected` | voice-doctor lints literal prompts, including module-level string constants passed by name. |
