# Vapi reference

Checked against Vapi's live OpenAPI spec (`https://api.vapi.ai/api-json`) and docs on 2026-10-26. Paths are on the assistant object (`GET /assistant/{id}`). `audit_config.py` and `lint_prompt.py --agent-json` read a Vapi assistant export directly.

Doc pages: assistants API https://docs.vapi.ai/api-reference/assistants/get · speech configuration https://docs.vapi.ai/customization/speech-configuration · idle messages and hooks https://docs.vapi.ai/assistants/idle-messages · call timeouts https://docs.vapi.ai/documentation/assistants/conversation-behavior/call-timeout-settings · multilingual https://docs.vapi.ai/customization/multilingual

## Where things live

| Concept | Field | Units, default, notes |
|---|---|---|
| First message | `firstMessage`, `firstMessageMode` | Mode: `assistant-speaks-first` (default), `assistant-speaks-first-with-model-generated-message`, `assistant-waits-for-user`. `firstMessageInterruptionsEnabled` default false. |
| System prompt | `model.messages[]` with `role: "system"` | There is no `systemPrompt` field in the current schema. |
| LLM | `model.provider`, `model.model`, `model.temperature` (0–2, default 0.5), `model.maxTokens` (50–10000, default 250), `model.reasoningEffort` | Keep reasoning `none` or `low` on live calls. |
| STT | `transcriber.provider`, `.model`, `.language` | Deepgram `transcriber.endpointing` is ms, 10–500, default 10. Keywords: Deepgram `keyterm[]`. |
| TTS | `voice.provider` (`11labs`, `cartesia`, `azure`, `vapi`, …), `voice.voiceId`, `voice.model`, `voice.language` | |
| End of turn | `startSpeakingPlan.waitSeconds` (s, 0–5, default 0.4), `.smartEndpointingPlan.provider` (`vapi`, `livekit`, `custom-endpointing-model`), `.transcriptionEndpointingPlan.onPunctuationSeconds` (0.1) / `onNoPunctuationSeconds` (1.5) / `onNumberSeconds` (0.5) | Vapi recommends LiveKit endpointing for English only; use `vapi` for other languages. Raise `waitSeconds` above 1.0 for callers who pause. |
| Interruption | `stopSpeakingPlan.numWords` (0–10, default 0), `.voiceSeconds` (0–0.5 s, default 0.2, used when numWords is 0), `.backoffSeconds` (default 1) | At 0, any 0.2 s of sound interrupts. Raise numWords so "okay" doesn't stop the agent. |
| Silence / "are you there?" | `hooks[]` with `on: "customer.speech.timeout"`, `options.timeoutSeconds` (1–1000, default 7.5), `triggerMaxCount` (default 3), `do: [{type: "say", exact: [...]}, {type: "tool", tool: {type: "endCall"}}]` | `silenceTimeoutSeconds` and `messagePlan.idleMessages` appear in guides but not in the current schema. |
| Max duration | `maxDurationSeconds` | s, 10–43200, **default 600**. |
| Voicemail | `voicemailDetection` (`"off"` or a provider plan: vapi, google, openai, twilio), `voicemailMessage` | **Off by default.** Without `voicemailMessage` the call hangs up on detection. |
| End call | `model.tools[{type: "endCall"}]`, `endCallMessage`, `endCallPhrases[]` | |
| Transfer | `model.tools[{type: "transferCall", destinations: [...]}]` | `forwardingPhoneNumber` is not in the current schema. |
| Outcomes | `server.url` (+ `serverMessages[]`, which includes `end-of-call-report`), `artifactPlan.structuredOutputIds[]` / `structuredOutputs[]` | `analysisPlan` is deprecated. |
| Speech chunking | `voice.chunkPlan.enabled` (default true), `.minCharacters` (1–80, default 30), `.punctuationBoundaries[]` (includes "।") | |
| Number formatting | `voice.chunkPlan.formatPlan.enabled`, `.numberToDigitsCutoff` (default 2025), `.replacements[]` | No rupee formatter; write amounts the way the voice should say them. |
| Background | `backgroundSound` (`off`, `office`, or a URL; office by default on phone), `backgroundSpeechDenoisingPlan` | |

Legacy fields not in the current schema: `silenceTimeoutSeconds`, `messagePlan.idleMessages` / `idleTimeoutSeconds`, `endCallFunctionEnabled`, `backchannelingEnabled`, `backgroundDenoisingEnabled`, `forwardingPhoneNumber`, `model.systemPrompt`. Older assistants may still return them; confirm behaviour on a test call before relying on them.

## Indian languages on Vapi

- **No native Sarvam provider.** Sarvam is only reachable through `custom-transcriber` / `custom-voice`.
- **STT**:
  - Deepgram has hi, hi-Latn, ta, te, kn, mr, bn, ur, en-IN, multi; **no ml, gu, pa**.
  - Azure has hi, ta, te, kn, ml, mr, bn, gu, pa, ur, en-IN (`-IN` locales).
  - 11labs Scribe, Soniox, Cartesia and Vapi's own STT accept as, bn, gu, hi, kn, ml, mr, or, pa, ta, te, ur.
- **TTS**:
  - Cartesia `voice.language`: bn, gu, hi, kn, ml, mr, or, pa, ta, te, ur.
  - Vapi voice: hi, ta, bn, gu, kn, ml, mr, pa, te.
  - Rime: hi, ta.
  - ElevenLabs Flash/Turbo v2.5: hi and ta only.
  - Azure: locale is set by the voiceId.
- **Multilingual**: Vapi recommends Deepgram nova-3 with `language: "multi"`. Which languages `multi` covers on Vapi is not documented.
