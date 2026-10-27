"""Regression tests for voice-doctor's scripts. Run: python3 -m unittest discover tests"""

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "voice-doctor", "scripts"))

from apply_changes import apply, method_for  # noqa: E402
from audit_config import audit, expected_minutes  # noqa: E402
from scorecard import badge, checkup, svg  # noqa: E402
from test_calls import scenarios, settings  # noqa: E402
from vocab import build as build_vocab, change_file  # noqa: E402
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

    def test_template_leftovers(self):
        prompt = "You are Priya, a ***REMOVED*** calling from Acme Store.\nGreeting: Namaste {customer_name} ji, main Priya bol rahi hoon."
        welcome = "Namaste {customer_name} ji, main Priya bol rahi hoon Acme Store se."
        found = rules(lint(prompt, welcome, None, "sarvam-v3").findings)
        self.assertIn("placeholder-text", found)
        self.assertIn("greeting-repeated", found)

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

    def test_flat_live_shape_and_defaults(self):
        # Bolna's GET /v2/agent returns the agent flat (no agent_config wrapper).
        agent = load("cod-confirmation", "agent.json")
        flat = {**agent["agent_config"], "agent_prompts": agent["agent_prompts"]}
        flat["tasks"][0]["task_config"].update(hangup_after_silence=10, check_if_user_online=True,
                                               trigger_user_online_message_after=10,
                                               check_user_online_message="Hey, are you still there")
        found = rules(audit(flat, None).findings)
        self.assertIn("call-cut-off", found)
        self.assertIn("online-check-language", found)
        self.assertNotIn("silence-hangup-before-check", found)  # Bolna's own defaults: 10 and 10

    def test_placeholder_webhook_and_transfer_promise(self):
        agent = load("cod-confirmation", "agent.json")
        agent["agent_config"]["webhook_url"] = "https://your-domain.com/api/bolna/webhook"
        agent["agent_prompts"]["task_1"]["system_prompt"] += "\nIf they ask for a human, transfer them to customer care."
        found = rules(audit(agent, None).findings)
        self.assertIn("webhook-placeholder", found)
        self.assertIn("transfer-promise", found)

    def test_default_hangup_check(self):
        agent = load("cod-confirmation", "agent.json")
        tc = agent["agent_config"]["tasks"][0]["task_config"]
        tc["hangup_after_LLMCall"] = True
        self.assertIn("default-hangup-check", rules(audit(agent, None).findings))
        tc["call_cancellation_prompt"] = "End the call only after the closing line."
        self.assertNotIn("default-hangup-check", rules(audit(agent, None).findings))

    def test_expected_minutes_ignores_unrelated_durations(self):
        self.assertIsNone(expected_minutes("Ask them to arrive 10 minutes early."))
        self.assertEqual(expected_minutes("This call should take 2-3 minutes."), 3)


SCRIPTS = os.path.join(ROOT, "skills", "voice-doctor", "scripts")


def run_script(*args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, args[0]), *args[1:]], capture_output=True, text=True)


class CiModeTests(unittest.TestCase):
    def test_min_score_sets_exit_code(self):
        agent = os.path.join(EX, "cod-confirmation", "agent.json")
        self.assertEqual(run_script("audit_config.py", agent, "--min-score", "70").returncode, 1)
        self.assertEqual(run_script("audit_config.py", agent, "--min-score", "0").returncode, 0)
        self.assertEqual(run_script("lint_prompt.py", "--agent-json", agent, "--min-score", "90").returncode, 1)

    def test_github_annotations(self):
        agent = os.path.join(EX, "cod-confirmation", "agent.json")
        out = run_script("audit_config.py", agent, "--format", "github").stdout
        self.assertIn("::error file=", out)
        self.assertIn("title=voice-doctor call-cut-off", out)
        out = run_script("lint_prompt.py", "--agent-json", agent, "--format", "github").stdout
        self.assertIn("title=voice-doctor romanised-indic", out)


class ScorecardTests(unittest.TestCase):
    def test_before_after_card(self):
        import xml.etree.ElementTree as ET
        agent = load("cod-confirmation", "agent.json")
        merged, _ = apply(agent, load("cod-confirmation", "config-changes.json"))
        before, after = checkup(agent), checkup(merged)
        card = svg(before, after)
        ET.fromstring(card)  # well-formed
        self.assertIn(f">{before['config']}<", card)
        self.assertIn(f">{after['config']}<", card)
        self.assertIn("Calls cut off mid-conversation", card)  # a fixed problem, in plain words
        self.assertIn("Fixed", card)

    def test_single_agent_card_and_badge(self):
        import xml.etree.ElementTree as ET
        card = svg(checkup(load("appointment-reminder", "agent.json")), None)
        ET.fromstring(card)
        self.assertIn("Top problems", card)
        self.assertTrue(badge(94).endswith("94%2F100-brightgreen"))
        self.assertTrue(badge(30).endswith("-red"))


class FleetTests(unittest.TestCase):
    def test_export_and_fleet_audit(self):
        import tempfile
        import bolna_api
        cod, appt = load("cod-confirmation", "agent.json"), load("appointment-reminder", "agent.json")
        flat = {aid: {**a["agent_config"], "agent_prompts": a["agent_prompts"]}
                for aid, a in (("aaaa1111-x", cod), ("bbbb2222-y", appt))}

        def fake_get(path, params=None):
            if path == "/v2/agent/all":
                return [{"id": k, "agent_name": v["agent_name"]} for k, v in flat.items()]
            return flat[path.rsplit("/", 1)[-1]]

        with tempfile.TemporaryDirectory() as d:
            original, bolna_api.get = bolna_api.get, fake_get
            try:
                written = bolna_api.export(d)
            finally:
                bolna_api.get = original
            self.assertEqual(len(written), 2)
            self.assertTrue(any(os.path.basename(p).startswith("cod-confirmation-acme-bazaar-aaaa1111") for p in written))
            out = run_script("audit_config.py", d)
            self.assertEqual(out.returncode, 0)
            self.assertIn("2 agents, worst first", out.stdout)
            first_row = out.stdout.splitlines()[4]
            self.assertTrue(first_row.startswith("COD Confirmation"))  # worst first
            self.assertEqual(run_script("audit_config.py", d, "--min-score", "60").returncode, 1)


class PlatformTests(unittest.TestCase):
    def test_detect_and_extract(self):
        from lint_prompt import detect_platform, extract_agent_text
        self.assertEqual(detect_platform(load("cod-confirmation", "agent.json")), "bolna")
        vapi = load("vapi-emi-reminder", "assistant.json")
        retell = load("retell-emi-reminder", "agent.json")
        self.assertEqual(detect_platform(vapi), "vapi")
        self.assertEqual(detect_platform(retell), "retell")
        v = extract_agent_text(vapi)
        self.assertIn("Acme Finance", v["prompt"])
        self.assertTrue(v["welcome"].startswith("Namaste"))
        self.assertEqual(v["tts"], "elevenlabs")
        r = extract_agent_text(retell)
        self.assertIn("EMI", r["prompt"])
        self.assertTrue(r["multilingual"])

    def test_vapi_audit(self):
        a = audit(load("vapi-emi-reminder", "assistant.json"), None)
        found = rules(a.findings)
        for rule in ("call-cut-off", "llm-reasoning-effort", "tts-language-unsupported", "smart-endpointing-language",
                     "interrupt-too-easy", "online-check-language", "voicemail-off", "no-outcome-capture",
                     "transfer-promise", "legacy-fields", "multilingual-off"):
            self.assertIn(rule, found)
        self.assertEqual(a.summary["platform"], "vapi")
        self.assertIn("speakability_score", a.summary)

    def test_retell_audit(self):
        a = audit(load("retell-emi-reminder", "agent.json"), None)
        found = rules(a.findings)
        for rule in ("call-cut-off", "platform-language-unsupported", "stt-language-unsupported",
                     "tts-language-unsupported", "silence-hangup-long", "interrupt-too-hard", "voicemail-off",
                     "no-outcome-capture", "transfer-promise", "deprecated-model-fields", "online-check-off"):
            self.assertIn(rule, found)
        self.assertNotIn("switch-rule-with-multilingual", rules(lint(
            "Reply in the caller's language.", None, None, "elevenlabs", True, "retell").findings))

    def test_other_platforms_patch_only(self):
        merged, changed = apply(load("vapi-emi-reminder", "assistant.json"),
                                {"maxDurationSeconds": 300, "voicemailDetection": {"provider": "vapi"}})
        self.assertEqual(merged["maxDurationSeconds"], 300)
        self.assertTrue(all(c["method"] == "PATCH" for c in changed))
        self.assertNotIn("call-cut-off", rules(audit(merged, None).findings))


class TestCallTests(unittest.TestCase):
    def test_tailored_to_agent(self):
        cod = load("cod-confirmation", "agent.json")
        ids = {s["id"] for s in scenarios(cod, load_executions(load("cod-confirmation", "executions.json")))}
        for sid in ("happy-path", "someone-else", "silence", "dictation", "scam-worry", "other-language", "long-call", "voicemail"):
            self.assertIn(sid, ids)
        self.assertTrue(any(i.startswith("replay-") for i in ids))
        appt = scenarios(load("appointment-reminder", "agent.json"))
        self.assertEqual(appt[0]["language"], "kn")
        self.assertNotIn("scam-worry", {s["id"] for s in appt})  # no money in a dental reminder
        silence = next(s for s in appt if s["id"] == "silence")
        self.assertTrue(any("check may never play" in x for x in silence["expect"]))  # hang-up 4 s < check 10 s

    def test_platform_timers(self):
        v = settings(load("vapi-emi-reminder", "assistant.json"))
        self.assertEqual((v["platform"], v["online_check"], v["cap"]), ("vapi", 8, 120))
        r = settings(load("retell-emi-reminder", "agent.json"))
        self.assertEqual((r["platform"], r["hangup"], r["online_check"]), ("retell", 600, None))

    def test_dry_run_transcripts_count_as_answered(self):
        dry = [{"id": "busy", "transcript": "assistant: **Order #AB-12345** confirm karein?\nuser: busy hoon"}]
        s = analyse(dry, load("cod-confirmation", "agent.json"))
        self.assertEqual(s["answered"], 1)
        self.assertIn("unspeakable-output", rules(s["findings"]))


class VocabTests(unittest.TestCase):
    def test_keywords_and_watchlist(self):
        r = build_vocab(load("cod-confirmation", "agent.json"))
        self.assertEqual(r["keywords"], ["Acme Bazaar", "COD"])
        watch = {w["term"]: w["risk"] for w in r["pronunciation_watchlist"]}
        self.assertEqual(watch["COD"], "may be read as a word")
        self.assertIn("Neha", watch)  # the agent says its own name, but callers don't need it boosted
        appt = build_vocab(load("appointment-reminder", "agent.json"))
        self.assertIn("SmileCare Dental Clinic", appt["keywords"])
        self.assertNotIn("Kavya", appt["keywords"])

    def test_wasted_existing_keywords_and_change_files(self):
        agent = load("cod-confirmation", "agent.json")
        agent["agent_config"]["tasks"][0]["tools_config"]["transcriber"]["keywords"] = "Neha, Namaste, Acme Bazaar"
        r = build_vocab(agent)
        self.assertEqual(sorted(r["wasted"]), ["Namaste", "Neha"])
        merged, _ = apply(agent, change_file(agent, r))
        self.assertEqual(merged["agent_config"]["tasks"][0]["tools_config"]["transcriber"]["keywords"], "Acme Bazaar, COD")
        vapi = load("vapi-emi-reminder", "assistant.json")
        self.assertEqual(change_file(vapi, build_vocab(vapi)), {"transcriber": {"keyterm": ["Acme Finance", "EMI"]}})
        retell = load("retell-emi-reminder", "agent.json")
        self.assertIn("boosted_keywords", change_file(retell, build_vocab(retell))["agent"])


class ApplyChangesTests(unittest.TestCase):
    def test_merge_scores_and_methods(self):
        agent = load("cod-confirmation", "agent.json")
        merged, changed = apply(agent, load("cod-confirmation", "config-changes.json"))
        tc = merged["agent_config"]["tasks"][0]["task_config"]
        self.assertEqual(tc["call_terminate"], 240)
        self.assertEqual(tc["hangup_after_silence"], 15)  # untouched siblings survive
        self.assertEqual(merged["agent_config"]["tasks"][0]["tools_config"]["transcriber"]["provider"], "deepgram")
        self.assertGreater(audit(merged, None).score, audit(agent, None).score + 40)
        methods = {c["field"].split(".")[-1]: c["method"] for c in changed}
        self.assertEqual(methods["buffer_size"], "PATCH")
        self.assertEqual(methods["call_terminate"], "PUT")
        self.assertEqual(agent["agent_config"]["tasks"][0]["task_config"]["call_terminate"], 90)  # input untouched

    def test_flat_agent_wrapped_changes_and_null_removes(self):
        agent = load("cod-confirmation", "agent.json")
        flat = {**agent["agent_config"], "agent_prompts": agent["agent_prompts"]}
        changes = {"agent_config": {"agent_welcome_message": "नमस्ते, क्या मेरी बात {{customer_name}} जी से हो रही है?",
                                    "webhook_url": None}}
        merged, changed = apply(flat, changes)
        self.assertNotIn("agent_config", merged)
        self.assertNotIn("webhook_url", merged)
        self.assertTrue(merged["agent_welcome_message"].startswith("नमस्ते"))
        self.assertTrue(all(c["method"] == "PATCH" for c in changed))
        self.assertEqual(method_for("agent_prompts.task_1.system_prompt"), "PATCH")


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
