# Speech engine facts

Verified against vendor docs on 2026-10-17. Vendors change fast and some of their own pages disagree; where they do, it's marked **conflict** and the safe move is a test call. Model strings in `code` are as Bolna's config names them unless noted.

## Contents
- Language support at a glance
- Sarvam: Bulbul TTS, Saaras STT
- Cartesia Sonic
- Deepgram Nova-3 and Aura
- ElevenLabs Flash
- Deadlines and deprecations

## Language support at a glance

| | hi | kn | ta | te | ml | mr | bn | gu | pa | od |
|---|---|---|---|---|---|---|---|---|---|---|
| Sarvam STT `saaras:v4` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Sarvam TTS `bulbul:v4-flash` | ✓ | ✓¹ | ✓¹ | ✓¹ | ✗ | ✓ | ✓ | ✓ | ✓ | ✗ |
| Sarvam TTS `bulbul:v3` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Deepgram `nova-3` (monolingual) | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ | ✓ | ? |
| Deepgram `nova-3` `multi` | ✓ only Indian language | | | | | | | | | |
| Cartesia `sonic-3` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 3.6+ |
| ElevenLabs `eleven_flash_v2_5` | ✓ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ |
| ElevenLabs `eleven_v4_turbo` / `eleven_v3_conversational` | ✓ | ✓ | ✓ | ? | ? | ? | ? | ? | ? | ? |

¹ Sarvam calls the v4 Flash Kannada, Tamil and Telugu voice rosters "narrow — audition carefully". Malayalam and Odia have no v4 Flash voices yet; Sarvam says keep that traffic on v3.

Deepgram's Indian-language support beyond Hindi is newer and less battle-tested than Sarvam's for Indian phone audio; for Kannada, Tamil, Telugu and Malayalam calls, Sarvam STT is the default recommendation.

## Sarvam

Docs: https://docs.sarvam.ai (Bulbul model page, v4 Flash best-practice guide, v3 best practices, Saaras model page).

### Bulbul TTS
- Models: `bulbul:v4-flash` (recommended), `bulbul:v3`, `bulbul:v2` (legacy). No plain `bulbul:v4`.
- Voices: v4 Flash speakers are `<name>_<lang>_<style>`, e.g. `ritu_hi_customer`, `simran_enhi_customer`. Short v2/v3 names (`anushka`, `shubh`) are **not valid on v4 Flash**, and Bolna notes v3 voice ids don't work on v4 Flash. Use `_enhi_` voices only for genuinely mixed Hindi-English speech.
- `pace` 0.5–2.0 (v3/v4 Flash). `temperature` 0.01–1.0, default 0.6; v3 guide suggests 0.3–0.5 for IVR/banking, 0.6 for agents. **Conflict**: the v4 Flash guide says temperature is ignored on v4 Flash.
- `enable_preprocessing`: API reference says v2 only; the v4 Flash guide recommends `true` on v4 Flash to normalise numbers, dates, currency and mixed-script text. **Conflict**: test on a real call.
- Numbers: the v4 Flash guide says don't hand-expand numbers, dates or currency; write `₹5,00,000` and `15/03/2026` with Indian grouping. v2 with preprocessing reads "Rs. 1,00,000" as "rupees one lakh". Phone numbers, OTPs, emails and abbreviations are undocumented.
- Script: "Romanised Indic input degrades quality". Indic words in native script, English words in Latin script inside the sentence.
- Punctuation: commas for short pauses, `।` to end Indic sentences, `…` sparingly. **No SSML.**
- Limits: 2,500 characters per REST request (v3/v4 Flash); WebSocket under 500 characters per message recommended for low latency. Buffer LLM output to sentence boundaries.
- Pronunciation dictionaries: `dict_id` (v3, v4 Flash).
- Latency: no millisecond figure in the docs.

### Saaras / Saarika STT
- `saaras:v4` is the default and recommended model; `saaras:v3` still available. `saarika:v2.5` and `saaras:v2.5` are deprecated (Bolna still accepts them). Migrate.
- Modes: `transcribe` (native script, normalised numbers), `translate` (English out), `verbatim` (keeps fillers and spoken numbers), `translit` (Latin script), `codemix` (English words in Latin, Indic in native script).
- `language_code="unknown"` auto-detects (Sarvam API; on Bolna the transcriber `language` is an ISO 639-1 code like `hi`).
- Keyword biasing: `keyterms` (max 50 terms × 64 characters), **saaras:v4 only**. On Bolna this is the transcriber `keywords` string. Bolna notes Sarvam may return boosted English terms in Devanagari.

## Cartesia Sonic

Docs: https://docs.cartesia.ai (TTS models, SSML tags, prompting tips, text normalisation, WebSocket buffering).

- Bolna model strings: `sonic-3.6`, `sonic-3.5`, `sonic-3`. Cartesia now recommends `sonic-3.6`.
- 42 languages on Sonic-3 including hi, bn, ta, te, kn, ml, mr, gu, pa; 3.6 adds or, ur.
- Hinglish: code-switching supported. Set `language: "hi"` even for romanised text. Normalisation: `hi-IN` for pure Devanagari, `en-IN` for romanised Hindi. **Devanagari mixed with romanised Hindi in one text is not supported.** On 3.6+, set `locale` or `language`, not both. Unverified whether `normalization`/`locale` work on older sonic-3 snapshots.
- Tags: `<speed ratio="0.6–1.5"/>`, `<volume ratio="0.5–2.0"/>`, `<break time="500ms"/>` (prefer punctuation; stacked breaks can cause glitches), `<spell>ABC123</spell>` for codes, `<emotion value="…"/>` (beta, English list). While streaming, a whole tag must arrive in one chunk or it gets read aloud.
- Numbers: leave conventional written forms; the normaliser handles them. Codes and OTPs: `<spell>` or space/comma-delimited digits. ₹, lakh and crore handling isn't documented.
- Writing: end every chunk with `.`, `?` or `!`; capitals only for acronyms you want spelled. Cartesia's own starter prompt bans markdown, bullets, headers, bold, JSON, emoji and special characters.
- Pronunciation: `pronunciation_dict_id`.
- Latency: "under 90 ms" is marketing; the docs give no number.

## Deepgram

Docs: https://developers.deepgram.com/docs (models-languages-overview, multilingual-code-switching, keyterm, endpointing, smart-format).

- Bolna STT strings: `nova-3`, `nova-3-medical`, `nova-2`, `nova-2-phonecall`, `nova-2-conversationalai`, `flux-general-en`, `flux-general-multi`. TTS: `aura-2`.
- Nova-3 monolingual: hi, bn, ta, te, kn, mr, gu, pa. **No Malayalam.** `multi` (code-switching) covers 10 languages; Hindi is the only Indian one. Deepgram recommends `endpointing=100` for code-switching.
- `keyterm`: up to 500 tokens per request, 20–50 terms recommended; Nova-3 and Flux. Nova-2 uses `keywords`. Not updatable mid-stream on the India regional endpoint.
- `smart_format`: full formatting for English only. `numerals` isn't supported for Hindi in multilingual.
- Aura-2 TTS: check Indian-language support before using it for Indic calls (not verified here).

## ElevenLabs

Docs: https://elevenlabs.io/docs (models, text-to-speech convert, best-practices/prompting/normalization, agents prompting guide).

- `eleven_flash_v2_5`: 32 languages, **Hindi and Tamil only** among Indian languages; ~75 ms model latency (excluding network).
- `eleven_v4_turbo` and `eleven_v3_conversational` (both on Bolna): 74 languages per Bolna's ElevenLabs page; ElevenLabs' models page lists Kannada for v4 and v3. Check your language on ElevenLabs' list and test latency before switching; Sarvam remains the default for Indian languages.
- `eleven_turbo_v2_5` is deprecated ("functionally equivalent" to Flash). Use Flash.
- Normalisation: `apply_text_normalization` (`auto`/`on`/`off`). **Conflict**: the models page says it's off by default on Flash v2.5 and `on` is Enterprise-only; another page says it's on for all models. ElevenLabs shows Flash reading "$1,000,000" as "one thousand thousand dollars" and recommends normalising in the LLM: spell numbers and symbols as words.
- Pronunciation dictionaries: alias rules for Flash v2.5 (phoneme tags only work on `eleven_flash_v2`).
- Agents guide: keep replies under three sentences; digits and symbols like "@" mispronounce more often.

## Deadlines and deprecations (as of 2026-10-17)

- **Cartesia `sonic-3-2025-10-27` snapshot sunsets 20 October 2026.** Aliases `sonic-3-latest` and `sonic-3-preview` are deprecated. Move to `sonic-3.6`. If Bolna's `sonic-3` string maps to that snapshot, calls may break or change voice; switch to `sonic-3.6` and re-test.
- Sarvam `saarika:v2.5` / `saaras:v2.5`: deprecated.
- ElevenLabs Turbo v2.5: deprecated in favour of Flash.
- Sarvam Bulbul v3 reaches end of life on Sarvam's own Voice Agents product on 10 November 2026; it stays on the TTS API (and so on Bolna).
