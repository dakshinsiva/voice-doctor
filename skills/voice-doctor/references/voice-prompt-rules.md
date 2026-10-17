# Writing prompts for the ear

Use this when rewriting a system prompt or welcome message for a phone or web-call voice agent. Engine facts (which TTS wants which number format, which script, which languages) are in `providers.md`. Bolna config fields are in `bolna.md`.

## Contents
1. Why voice breaks chat prompts
2. The shape of a good voice prompt
3. Speaking rules, with before/after
4. Numbers, money, dates, codes (engine-dependent)
5. Indian languages, script and code-mixing
6. The welcome message
7. Situations every outbound prompt needs
8. Domain safety
9. Skeleton

---

## 1. Why voice breaks chat prompts

A chat user scans; a caller hears each word once, in order, at about two and a half words a second, and can't scroll back. Anything visual (lists, bold, links, tables, emojis) gets read as noise or silently dropped. Long turns hurt more on a call: callers interrupt, talk over the agent, or hang up. Speech-to-text also mishears, so the agent must expect wrong or partial input and recover.

So a voice prompt has three jobs a chat prompt doesn't: make the model's output speakable, keep turns short enough for a conversation, and plan for the messy edges of a real call (silence, noise, wrong person, "I'm busy").

## 2. The shape of a good voice prompt

Markdown headings inside the system prompt are fine: the model reads them, the caller never hears them. Order matters, because models weight the start of the prompt more.

1. **Who you are and why you're calling**, in two or three lines.
2. **How you speak**: output rules (section 3).
3. **Language and script** (section 5).
4. **Call flow**: numbered steps, one question per step, with what to do for each likely answer.
5. **Situations**: busy, wrong person, voicemail, not understood, upset caller, "are you a robot?" (section 7).
6. **Limits** for the domain (section 8).
7. **Ending**: when to end and the exact closing line.
8. **Facts**: only what the agent needs to say. Long reference material belongs in the platform's knowledge base.

## 3. Speaking rules

Put a section like this near the top of every voice prompt, adapted to the persona:

> **How you speak.** You are on a phone call, so everything you write is spoken aloud by a voice engine. Use plain spoken sentences only: no lists, headings, bold, emojis, brackets or symbols. Keep each reply to one or two short sentences, then stop and let the caller talk. Ask one question at a time. Start with the point. Use everyday words, the way a polite person talks on the phone.

Why each rule earns its place:

- **One or two sentences per turn.** Turn length is the biggest lever on how natural a call feels. Short turns also start playing sooner and get interrupted less. Bolna's own prompting guide uses "You will not speak more than 2 sentences at a time."
- **One question per turn.** With two questions, callers answer the last one and the first is lost. The transcript then looks like the agent ignored the answer.
- **Start with the point.** "Your order will arrive on Friday" beats "So I just wanted to inform you that, as per our records, your order…". Callers decide in the first few words whether to listen.
- **Acknowledge, then move.** A short acknowledgement ("Achha, theek hai.", "Got it.") before the next question shows the agent heard. Vary it; the same one every turn sounds robotic.
- **Closed questions for data, open questions for feelings.** "Should I confirm the order?" is easier for speech-to-text and the caller than "What would you like to do?". Use open questions only where you want the caller to talk.
- **Read back anything that matters.** Amounts, dates, times, pincodes, names: "So that's delivery on Friday to pincode five six zero zero seven eight, right?" This catches mishearing and gives post-call extraction a clean line to parse.
- **Never ask callers to spell or dictate** emails, URLs or long codes. Offer to send or receive them on WhatsApp or SMS, or use keypad (DTMF) entry for OTPs and account numbers if the platform supports it.
- **Don't read links or emails.** Say "I'll send the link on WhatsApp", and make sure something actually sends it.
- **When interrupted, stop and respond to what they said.** Don't restart the sentence that was cut off.

Before (chat style):
> "Your order **#AB-20931** for ₹1,499 (2 items) will be delivered by 18/10 — please keep exact change ready! Track it at https://shop.example/track 📦"

After (spoken, for Sarvam Bulbul v4 Flash or Cartesia, which read written amounts well):
> "Your order of two items, for ₹1,499, will reach you by Saturday, 18 October. Please keep the cash ready. I'll send the tracking link on WhatsApp."

Notice what changed: no order ID read aloud (callers can't use it), no symbols or emoji, a weekday with the date, one instruction per sentence, and the link moved to a message.

## 4. Numbers, money, dates, codes

How to write numbers depends on the voice engine. Vendors disagree, so check the agent's synthesizer before writing the rule (`providers.md` has details):

| Engine | Money, dates, everyday numbers | Phone numbers, OTPs, codes |
|---|---|---|
| Sarvam Bulbul v4 Flash | Keep conventional written forms with Indian grouping: ₹5,00,000, 15 March 2026. Sarvam says not to hand-expand them. | Undocumented by Sarvam. Write digits in small groups separated by commas or spaces, and test. |
| Sarvam Bulbul v2 | Turn on `enable_preprocessing` (reads "Rs. 1,00,000" as "rupees one lakh"), or write in words. | As above. |
| Sarvam Bulbul v3 | Unclear in Sarvam's docs. Test both written and spelled-out forms on a real call. | As above. |
| Cartesia Sonic 3.x | Conventional written forms; its normaliser handles them. ₹, lakh and crore aren't documented, so test them. | Space- or comma-delimited digits, or `<spell>…</spell>` (whole tag in one chunk when streaming). |
| ElevenLabs Flash v2.5 | Spell out in words in the prompt output. ElevenLabs recommends normalising in the LLM; its own normaliser is off by default on Flash. | Digits as words in groups: "nine eight four five zero, one two three four five". |
| Unknown or other | Spell out, then test. | Digits in small groups. |

Whatever the engine:
- **Never pass machine formats** to the model or the voice: ISO dates (`2026-10-20T17:30:00+05:30`), raw epoch times, unformatted big numbers (`150000`), currency codes (`INR 1499.00`). Format dynamic variables before the call.
- **Add the weekday** to dates ("Saturday, 18 October"). It's what people anchor on.
- **Structured values need a spoken form.** An item list or full address dropped raw into a scripted line gets read verbatim ("1. Cotton Kurta (Blue, L) - ₹999"). Pass a ready-made phrase ("एक blue kurta और एक dupatta"), or tell the model to summarise: "mention the items in one short phrase; say only the building and area of the address".
- **Indian conventions**: lakh and crore, not hundred-thousand or million. Hindi speakers say "saadhe" (+½), "sawa" (+¼), "paune" (−¼), "dedh" (1½), "dhai" (2½); "saadhe paanch baje" for 5:30.
- **Long codes are a smell.** Order IDs, AWB numbers and reference numbers are useless read aloud. Send them by message.
- **Read-backs for numbers the caller gives**, digit by digit, so mishearing gets caught.
- **Units**: write them out (kilos, grams, litres, milligrams) unless you've tested the engine reads the abbreviation correctly.

Bolna's guidance adds: read alphanumerics (codes mixing letters and digits) character by character in English, and use DTMF for OTPs.

## 5. Indian languages, script and code-mixing

Real Indian callers mix languages. The prompt and the config must agree on how.

**Who switches the language?** On platforms where the transcriber and voice are set to one language (Bolna's default), the model writing Kannada while the voice is set to Hindi gives garbled audio. On Bolna, language switching belongs in `multilingual_config` (one transcriber, synthesizer and prompt per language), and Bolna says not to put switching instructions in the prompt. Code-mixing alone (Hinglish) does not trigger a switch. So:
- **One main language with English words mixed in** (Hinglish, Kanglish): one prompt, one language setting, no switching rules. Hindi with English loanwords works on a normal Hindi voice (`<name>_hi_<style>`). Use a Sarvam `_enhi_` voice only when turns mix whole English and Hindi phrases; Sarvam says not for "only a few loan words". `_enhi_` covers Hindi and English only, so Kanglish uses a Kannada (`kn`) voice.
- **Callers who may speak entirely different languages** (Hindi or Kannada or Tamil): use the platform's multilingual feature, with a prompt per language. Don't fake it with a prompt rule.
- **Stacks with multilingual STT and TTS end to end**: a prompt rule ("reply in the caller's language") can work, but test it on real calls.

**Script.** Sarvam says romanised Indic input degrades quality, and Bolna agrees: write Indic words in native script (Devanagari, Kannada, Tamil…) and keep English words in Latin script inside the sentence: "आपका order confirm हो गया है।". Cartesia is the exception: it handles Devanagari or romanised Hindi (set `language: "hi"`), but not a mix of both in one text. Put the script rule in the prompt explicitly ("Write Hindi in Devanagari. Keep English words like order, delivery, payment in English letters; don't translate them into formal Hindi."), because models drift to romanised Hindi. Write the persona's and brand's names the way the voice should say them in fixed lines (नेहा rather than Neha inside a Devanagari sentence, unless a test call shows the Latin spelling sounds right).

**Sound like people talk.**
- **Conversational Hindi, not shuddh or IVR Hindi.** "आपका order कल तक पहुँच जाएगा" not "आपका आदेश कल तक वितरित किया जाएगा". Textbook Hindi from a model sounds like a government announcement. Avoid अवगत, सुनिश्चित, प्रतीक्षा, सफलतापूर्वक and "क्या आप … करना चाहेंगे?"; keep कृपया for safety warnings. Prefer बताइए, भेज दूँ?, सही है?, ठीक है जी. Bolna advises keeping common English loanwords in Latin script rather than forcing a pure translation.
- **English words go through Hindi grammar.** English nouns slot in naturally ("order", "payment link"); verbs take a Hindi helper: "confirm कर दूँ?", "cancel हो गया", "address change करना है?". Not "Please confirm कीजिए your order".
- **No translated English idioms.** "आपका दिन शुभ हो" is a word-for-word "have a nice day" and sounds scripted; close with "ठीक है जी, धन्यवाद।" or "धन्यवाद, आपका order समय पर पहुँच जाएगा।".
- **Spoken Kannada, not written Kannada.** Use polite spoken Bengaluru–Mysuru forms (ಮಾಡ್ತೀನಿ, ಮಾಡ್ತಿದ್ದೀನಿ, ಮಾತಾಡಬಹುದಾ?, ಇದ್ರೆ, ಆಗುತ್ತೆ, ಹೇಳ್ತೀರಾ?) rather than written ones (ಮಾಡುತ್ತೇನೆ, ಮಾಡುತ್ತಿದ್ದೇನೆ, ಮಾತನಾಡಬಹುದೇ?, ಇದ್ದರೆ, ಆಗುತ್ತದೆ). Say "call ಮಾಡ್ತೀನಿ", not "ಕರೆ ಮಾಡುತ್ತೇನೆ". Use ನೀವು with polite imperatives (ಬನ್ನಿ, ಹೇಳಿ), and no slang (ಮಗ, ಗುರು). End Kannada sentences with ".", not "।". Kannada case endings attach to values, so pass times already in spoken Kannada ("ನಾಳೆ ಬೆಳಗ್ಗೆ ಹತ್ತೂವರೆಗೆ") instead of a bare "10:30".
- **Respect markers.** Hindi: आप (not तुम), "ji" after names. Kannada: ನೀವು, "avare" after names. Default to respectful unless the brand is deliberately casual.
- **Hindi verb gender must match the persona and the voice, in every tense.** A female persona says बोल रही हूँ, समझ गई, कर लेती हूँ, call करूँगी, कर सकती हूँ; a male one बोल रहा हूँ, समझ गया, करूँगा. Models drift mid-call, so put these examples in the prompt and pick a voice whose gender matches the persona's name. The caller gets आप with plural verbs (बता सकते हैं, रखिएगा), which is right for any gender. Kannada, Tamil and Telugu first-person verbs don't mark gender, so they need no such rule.
- **Short sentences, point first, tag questions.** "…वाले address पर ही होगी ना?", "ಗುರುವಾರ, ಸರಿನಾ?" sound like people; 30-word chains of clauses don't.
- **Punctuation for pauses**: commas for short pauses, "।" to end Hindi sentences (Sarvam's guidance). No SSML on Sarvam.
- **Mirror the caller's mix.** If the caller leans English, lean English; if they speak pure Hindi, drop some loanwords. Bilingual users prefer agents that code-mix the way they do.
- **Names and brand words**: add them to the transcriber's keyword list (Bolna `keywords`; Sarvam saaras:v4 and Deepgram Nova-3 support keyterm biasing) so they're recognised, and test how the voice says them.

## 6. The welcome message

On Bolna the welcome message (`agent_welcome_message`) is spoken straight through TTS before the caller says anything. It's the first impression.

- **Under about 25 words**, roughly ten seconds. Every extra second before the caller can speak raises hang-ups.
- **Who, from where, why, one question.** "नमस्ते {{customer_name}} जी, मैं नेहा, Acme Bazaar की AI assistant, आपके order के बारे में call कर रही हूँ। क्या अभी दो मिनट बात हो सकती है?" (Native script with English words in Latin, per section 5.)
- **Say it's an AI assistant.** Callers who find out later feel tricked, and it makes them forgiving when it mishears.
- **End on a yes/no question** so the caller knows it's their turn and the first reply is easy to transcribe.
- **No data question in the welcome.** Ask permission first; the flow asks the rest.
- **Check the register, not just the length.** A correct but written-style welcome sounds like an IVR: rewrite "ನಾಳೆಯ appointment ಬಗ್ಗೆ ಕರೆ ಮಾಡಿದ್ದೇನೆ. ಈಗ ಮಾತನಾಡಬಹುದೇ?" as "ನಾಳೆ appointment ಬಗ್ಗೆ call ಮಾಡ್ತಿದ್ದೀನಿ. ಈಗ ಎರಡು ನಿಮಿಷ ಮಾತಾಡಬಹುದಾ?". A romanised welcome going to a Sarvam voice must be rewritten in native script. Write every fixed line (welcome, closing, voicemail, safety lines) in full in the target language; don't leave translation to the model.
- **No personal details before the caller confirms who they are.** Order numbers, amounts, appointment details and addresses wait until the right person has said yes; a wrong number, a family member or a voicemail should learn nothing beyond who's calling and why.
- **Variables**: check every one is passed on every call (Bolna uses `{{name}}`; `{name}` also works). A missing value is read literally or skipped.

## 7. Situations every outbound prompt needs

Write each as a short branch in the prompt:

| Situation | What the agent should do |
|---|---|
| Busy / bad time | "No problem. When should I call back?" Confirm the time, end. |
| Wrong person / wrong number | Apologise in one sentence and end. Share no customer details. |
| Someone else answers | Ask if the customer is available; if not, offer a callback; share nothing personal. |
| Voicemail | One-sentence message with who and why, no order or account details, then end. Turn on the platform's voicemail detection too. |
| Not understood / noisy line | "Sorry, I didn't catch that. Could you say it again?" in simpler words. After two failures on the same question, skip it or offer a callback. |
| Silence | One check ("Hello, can you hear me?"), then end politely. The platform's silence timeout handles the rest. |
| "Are you a robot?" | Yes, honestly, and who you're calling for. Offer a human callback if they prefer. |
| Upset or angry caller | Acknowledge in one sentence, don't argue, offer a human, end gracefully. |
| Off-topic question | One short answer if it's easy and safe, then steer back. Don't invent facts. |
| Wants a human | Transfer or promise a callback, whichever the platform supports. Don't stall. |
| Wants no more calls | Confirm, thank them, end, and make sure it's captured for opt-out. |

## 8. Domain safety

Voice agents speak with authority, and callers act on what they hear. Write limits as positive instructions with concrete triggers; "never give medical advice" alone is too vague for a model to apply.

- **Money and identity**: never ask for OTPs, PINs, card numbers, CVV or passwords, and say so if the caller offers them. Scam-wary callers relax when the agent says it first. Collect payment only through links or verified flows.
- **Health**: no diagnosis, no medicine or dose changes. List red flags (chest pain, fainting, breathing trouble, thoughts of self-harm) and what to do: tell the caller to contact a doctor or emergency services now, flag the call for a human, end the flow.
- **Lending and collections**: no threats, no discussing the debt with anyone but the borrower, calling only in permitted hours, and a clear path to dispute.
- **Promises**: only promise what the system actually does. If the prompt says "I'll send it on WhatsApp", something must send it.

## 9. Skeleton

```markdown
# Who you are
You are {persona}, the AI assistant from {org}. You call {who} to {purpose}. You are polite, brief and practical. {Hindi: You are a woman; use feminine verb forms for yourself.}

# How you speak
You are on a phone call; everything you write is spoken aloud. Plain spoken sentences only: no lists, headings, bold, emojis, brackets or symbols. One or two short sentences per reply, then stop. One question at a time. Read back numbers and dates to confirm. Never read out links, emails or order IDs; offer to send them on WhatsApp.
{Number rule for this engine, from section 4.}

# Language
{Script rule from section 5, e.g. "Speak everyday Hindi. Write Hindi in Devanagari and keep English words like order, delivery and payment in English letters. Never translate them."}

# Call flow
1. Confirm you're speaking to {{customer_name}}. If not, see Situations.
2. ... one question per step, with what to do for each likely answer ...
N. Summarise in one sentence and close.

# Situations
Busy: ... Wrong person: ... Voicemail: ... Not understood: ... Wants a human: ...

# Limits
{domain limits with concrete triggers}

# Ending
End the call when {conditions}. Closing line: "{closing}"

# Facts you may need
{short list, formatted for the engine}
```

## Sources

- Sarvam Bulbul v4 Flash best-practice guide (script, loanwords, `_enhi_` voices, numbers, punctuation): https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/best-practice-guide-for-bulbul-v-4-flash
- Bolna, writing prompts in non-English languages: https://www.bolna.ai/docs/writing-prompts-in-non-english-languages.md
- Bolna prompting guide ("not more than 2 sentences at a time"): https://www.bolna.ai/docs/prompting/introduction.md
- Microsoft Research on code-mixing in conversational agents: https://www.microsoft.com/en-us/research/blog/cracking-code-mixing-an-important-step-in-making-human-computer-interaction-more-engaging/
- Bawa et al., "Do multilingual users prefer chat-bots that code-mix?" (CSCW 2020): https://www.microsoft.com/en-us/research/publication/do-multilingual-users-prefer-chat-bots-that-code-mix-lets-nudge-and-find-out/
- Parekh et al., CoNLL 2020, code-mixed dialogue: https://aclanthology.org/2020.conll-1.46
- Spoken vs written Kannada, Bengaluru Kannada: https://en.wikipedia.org/wiki/Kannada, https://en.wikipedia.org/wiki/Bengaluru_Kannada
- Kannada pronoun politeness (WALS 45A): https://wals.info/valuesets/45A-knd
- ElevenLabs agents prompting guide (short replies, digits and symbols): https://elevenlabs.io/docs/agents-platform/best-practices/prompting-guide
- Cartesia prompting tips (no markdown, punctuation, spelling codes): https://docs.cartesia.ai/build-with-cartesia/capability-guides/prompting-tips.md
