# LiveKit Agents reference

Checked against livekit-agents 1.8.9 source (released 2026-10-24) and docs.livekit.io on 2026-10-27. `audit_config.py` reads LiveKit agents straight from Python source (a `.py` file or a folder); nothing is imported or run.

Source: https://github.com/livekit/agents/tree/livekit-agents%401.8.9 · turn handling `livekit-agents/livekit/agents/voice/turn.py` · session `voice/agent_session.py` · tuning guide https://docs.livekit.io/agents/logic/turns/tuning.md · turn detector https://docs.livekit.io/agents/build/turns/turn-detector/ · noise cancellation https://docs.livekit.io/transport/media/noise-cancellation.md

**API change to know:** since 1.5.0 the flat `AgentSession` arguments (`min_endpointing_delay`, `allow_interruptions`, `turn_detection`, `preemptive_generation`, …) are deprecated in favour of `turn_handling=TurnHandlingOptions(...)`. Both forms work until 2.0; voice-doctor reads both.

| Concept | Where | Default, units, guidance |
|---|---|---|
| Turn detection | `TurnHandlingOptions(turn_detection=...)` or legacy `AgentSession(turn_detection=)` | Default `inference.TurnDetector()` (14 languages, **includes Hindi**). `livekit.plugins.turn_detector.english.EnglishModel()` is **English-only**; the text-based plugin is deprecated. |
| Endpointing | `endpointing={"mode": "fixed"/"dynamic", "min_delay", "max_delay"}`; legacy `min_endpointing_delay`, `max_endpointing_delay` | Seconds. With the audio detector, defaults are 0.3 / 2.5. Docs: start at `min_delay` 0.5 and raise it if the agent cuts people off. |
| Interruptions | `interruption={"enabled", "mode": "adaptive"/"vad", "min_duration": 0.5, "min_words": 0, "false_interruption_timeout": 2.0, "resume_false_interruption": True}`; legacy `allow_interruptions`, `min_interruption_words`, … | Keep `resume_false_interruption`. Raise `min_words` to ignore acknowledgements (needs STT). |
| Preemptive generation | `preemptive_generation={"enabled": True, "preemptive_tts": False, …}` | Docs: keep `preemptive_tts` off. |
| Caller goes quiet | `AgentSession(user_away_timeout=15.0)`; `None` disables. Event `user_state_changed` with `new_state == "away"` | Nothing is said unless you handle the event. |
| VAD | `silero.VAD.load(min_silence_duration=0.55, activation_threshold=0.5, …)` | Docs: the audio turn detector needs `min_silence_duration` ≥ 0.25 s (from docs; the check wasn't found in source). |
| Max call length | none built in | End stuck calls with your own timer and `session.shutdown()`. |
| LLM | `openai.LLM(model, temperature, max_completion_tokens, reasoning_effort, verbosity)` | If `reasoning_effort` is unset the plugin picks `none`/`minimal`; setting it higher slows every reply. |
| Sarvam | `sarvam.STT(language="en-IN", model="saaras:v4", mode="transcribe")`; `sarvam.TTS(target_language_code="en-IN", model="bulbul:v3", speaker=…)` | **Both default to English (en-IN)**: set `language="hi-IN"` / `target_language_code="hi-IN"` for Hindi. `saarika:v2.5` / `saaras:v2.5` are sunset. |
| Others | `deepgram.STT(model="nova-3", language="en-US", endpointing_ms=25)`; `elevenlabs.TTS(model="eleven_turbo_v2_5", language=)`; `cartesia.TTS(model="sonic-3", language="en")` | ElevenLabs' default model is the deprecated Turbo v2.5 (Hindi and Tamil only among Indian languages). |
| Noise cancellation | `session.start(room_options=room_io.RoomOptions(audio_input=room_io.AudioInputOptions(noise_cancellation=noise_cancellation.BVCTelephony())))` | Default none. Use `BVCTelephony()` for SIP calls (closed-source package; names from LiveKit's docs). |
| Prompt and greeting | `Agent(instructions=...)`; greeting in `on_enter` via `session.say(text)` (spoken as written) or `session.generate_reply(instructions=...)` | voice-doctor lints literal `instructions` and the `say()` text. |
