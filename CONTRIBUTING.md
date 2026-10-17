# Contributing to voice-doctor

Thanks for helping voice agents sound less like chatbots. The most useful contributions are real cases where a rule is wrong or missing.

## Ground rules

- **Redact everything.** No API keys, phone numbers, customer names or addresses in issues, examples or tests. Replace them before you paste.
- **Every fact needs a source.** Model names, defaults, language support and field names go in `skills/voice-doctor/references/` with a link to the vendor doc or source line and the date you checked it. If two vendor pages disagree, say so instead of picking one.
- **Native speakers decide language rules.** For Hindi, Kannada, Tamil, Telugu, Bengali and Marathi phrasing, include a before and after and why one sounds natural.

## Adding or changing a check

1. Change the script in `skills/voice-doctor/scripts/` (`lint_prompt.py`, `audit_config.py` or `call_stats.py`). Standard library only.
2. Add a test in `tests/test_scripts.py` that fails without your change.
3. If the check rests on a vendor fact, add it to the matching reference file with its source.
4. Run the tests:

```bash
python3 -m unittest discover tests
```

5. Open a PR that says what callers experience when the problem happens, and how you found it.

## Adding a platform

Config checks are Bolna-only today. For Vapi, Retell, LiveKit or Pipecat, add a reference file with the platform's settings mapped to the ones in `references/bolna.md` (endpointing, interruption threshold, max call length, voicemail detection, TTS buffering), then a script or a section in `SKILL.md` that uses it.

## Changing SKILL.md

Keep it short and explain *why* a rule exists; the model follows reasons better than commands. If you change behaviour, describe the before and after in the PR.
