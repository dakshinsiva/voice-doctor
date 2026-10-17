"""Regression tests for voice-doctor's scripts. Run: python3 -m unittest discover tests"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "voice-doctor", "scripts"))

from audit_config import audit, expected_minutes  # noqa: E402
from call_stats import analyse, load_executions  # noqa: E402
from lint_prompt import lint  # noqa: E402

EX = os.path.join(ROOT, "examples")


def load(*parts):
    with open(os.path.join(EX, *parts), encoding="utf-8") as fh:
        return json.load(fh)


def rules(findings):
    return {f.rule if hasattr(f, "rule") else f["rule"] for f in findings}


class LintTests(unittest.TestCase):
    def test_chat_style_prompt_scores_low(self):
        agent = load("cod-confirmation", "agent.json")
        prompt = agent["agent_prompts"]["task_1"]["system_prompt"]
        welcome = agent["agent_config"]["agent_welcome_message"]
        r = lint(prompt, welcome, {"customer_name", "order_id", "items", "order_amount", "address"}, "sarvam-v4")
        found = rules(r.findings)
        for rule in ("no-output-style-rule", "no-brevity-rule", "romanised-indic", "undefined-variable",
                     "multi-language-one-voice", "url-in-prompt", "stacked-questions"):
            self.assertIn(rule, found)
        self.assertLess(r.score, 40)

    def test_number_rules_depend_on_engine(self):
        line = 'Say: "Your total is ₹1,499 and it arrives on 18/10, please keep the cash ready."'
        self.assertNotIn("currency", rules(lint(line, None, None, "sarvam-v4").findings))
        self.assertIn("currency", rules(lint(line, None, None, "elevenlabs").findings))

    def test_language_handoff_is_not_switching(self):
        handoff = ("Speak Hindi. If the caller only speaks Kannada or Tamil, apologise in simple English, "
                   "offer a callback and end the call.")
        self.assertNotIn("multi-language-one-voice", rules(lint(handoff, None, None, "sarvam-v4").findings))
        switching = "Customers may speak Hindi, Kannada or Tamil. Always reply in the language the customer uses."
        self.assertIn("multi-language-one-voice", rules(lint(switching, None, None, "sarvam-v4").findings))

    def test_callback_alone_is_not_a_busy_branch(self):
        prompt = "If they can't come, say the clinic will call back to confirm a new time."
        self.assertIn("no-busy-or-wrong-person-rule", rules(lint(prompt, None, None).findings))

    def test_register_checks(self):
        kn = "ನಮಸ್ಕಾರ, ನಾಳೆಯ appointment ಬಗ್ಗೆ ಕರೆ ಮಾಡಿದ್ದೇನೆ. ಈಗ ಮಾತನಾಡಬಹುದೇ?"
        self.assertIn("written-kannada", rules(lint("x", kn, None, "sarvam-v4").findings))
        spoken_kn = "ನಮಸ್ಕಾರ, ನಾಳೆ appointment ಬಗ್ಗೆ call ಮಾಡ್ತಿದ್ದೀನಿ. ಈಗ ಮಾತಾಡಬಹುದಾ?"
        self.assertNotIn("written-kannada", rules(lint("x", spoken_kn, None, "sarvam-v4").findings))
        hi = "धन्यवाद, आपका दिन शुभ हो!"
        self.assertIn("stiff-hindi", rules(lint("x", hi, None, "sarvam-v4").findings))

    def test_clean_prompt_scores_high(self):
        prompt = ("# How you speak\nYou are on a phone call; everything you write is spoken aloud. Plain spoken sentences "
                  "only, no lists or markdown. Keep each reply to one or two short sentences. Ask one question at a time. "
                  "Read phone numbers digit by digit in small groups. If you didn't catch something, ask again. "
                  "If they are busy, offer a callback. End the call politely when done.")
        welcome = "Hello {{name}}, I'm Asha, the AI assistant from Acme Bazaar, about your order. Is now a good time?"
        r = lint(prompt, welcome, {"name"}, "cartesia")
        self.assertGreaterEqual(r.score, 90, [f.rule for f in r.findings])


class AuditTests(unittest.TestCase):
    def test_cod_agent(self):
        found = rules(audit(load("cod-confirmation", "agent.json"), None).findings)
        for rule in ("call-cut-off", "endpointing-too-low", "tts-voice-version", "llm-reasoning-effort",
                     "multilingual-off", "voicemail-off", "no-calling-hours"):
            self.assertIn(rule, found)

    def test_appointment_agent(self):
        a = audit(load("appointment-reminder", "agent.json"), None)
        found = rules(a.findings)
        for rule in ("tts-language-unsupported", "call-cut-off", "endpointing-too-high", "interrupt-too-hard",
                     "silence-hangup-short", "silence-hangup-before-check", "no-outcome-capture"):
            self.assertIn(rule, found)
        self.assertNotIn("no-calling-hours", found)
        self.assertEqual(a.summary["expected_minutes"], 3)

    def test_expected_minutes_ignores_unrelated_durations(self):
        self.assertIsNone(expected_minutes("Ask them to arrive 10 minutes early."))
        self.assertEqual(expected_minutes("This call should take 2-3 minutes."), 3)


class CallStatsTests(unittest.TestCase):
    def test_cod_calls(self):
        s = analyse(load_executions(load("cod-confirmation", "executions.json")), load("cod-confirmation", "agent.json"))
        found = rules(s["findings"])
        for rule in ("slow-llm", "calls-capped", "agent-cuts-in", "unspeakable-output", "romanised-output", "loops",
                     "dead-air"):
            self.assertIn(rule, found)
        self.assertEqual(s["answered"], 5)
        self.assertEqual(len(s["calls_at_duration_cap"]), 2)


if __name__ == "__main__":
    unittest.main()
