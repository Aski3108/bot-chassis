"""Gate 11: золотой .env.example рамы и старый минимальный конфиг."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from bot_chassis.config import BotChassisConfig
from bot_chassis.user_lifecycle import CANON_ALLOWED_UPDATES

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / "examples" / ".env.example"
TASK_TODO = ROOT / ".agents" / "TASK_TODO.md"

REQUIRED_KEYS = (
    "BOT_TOKEN",
    "SUPPORT_CHAT_ID",
    "AUDIT_CHAT_ID",
    "SUPPORT_THREAD_ID",
    "AUDIT_THREAD_ID",
    "OPS_THREAD_ID",
    "EVENTS_THREAD_ID",
    "CHASSIS_BOT_ID",
    "CHASSIS_ORIGIN_BOT_ID",
    "CHASSIS_DB_PATH",
)

FORBIDDEN_MARKERS = (
    "REVIEWS_",
    "REDIS",
    "RABBIT",
    "KAFKA",
    "BROKER",
    "YUKASSA",
    "CRYPTOBOT",
    "CHASSIS_AUDIT_CHAT_ID",
)


def _parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value
    return values


class TestGate11EnvCanon(unittest.TestCase):
    def test_example_has_chassis_keys_without_secrets_or_domain(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        values = _parse_env(text)
        for key in REQUIRED_KEYS:
            self.assertIn(key, values, key)
        self.assertEqual(values["BOT_TOKEN"], "")
        self.assertNotIn(":", values["BOT_TOKEN"])
        self.assertEqual(values["SUPPORT_CHAT_ID"], "")
        self.assertEqual(values["AUDIT_CHAT_ID"], "")
        for thread_key in (
            "SUPPORT_THREAD_ID",
            "AUDIT_THREAD_ID",
            "OPS_THREAD_ID",
            "EVENTS_THREAD_ID",
        ):
            self.assertEqual(values[thread_key], "")
        upper = text.upper()
        for marker in FORBIDDEN_MARKERS:
            self.assertNotIn(marker, upper)
        self.assertIn("BackupPolicy", text)
        self.assertIn("ReportingPolicy", text)

    def test_legacy_minimal_config_still_works(self) -> None:
        config = BotChassisConfig(bot_id="legacy")
        self.assertEqual(config.bot_id, "legacy")
        self.assertIsNone(config.audit_chat_id)
        self.assertIsNone(config.support_thread_id)
        self.assertIsNone(config.audit_thread_id)
        self.assertIsNone(config.ops_thread_id)
        self.assertIsNone(config.events_thread_id)
        self.assertIsNone(config.origin_bot_id)
        self.assertEqual(config.db_path, "bot_chassis.db")

    def test_canon_allowed_updates_include_membership(self) -> None:
        self.assertIn("my_chat_member", CANON_ALLOWED_UPDATES)

    def test_task_todo_stays_a_short_gate_queue(self) -> None:
        text = TASK_TODO.read_text(encoding="utf-8")
        self.assertIn("вторую техническую спецификацию", text)
        live = text.split("## Архив исходных девяти указаний", 1)[0]
        self.assertIn("Gate 11. Канон окружения и документации", live)
        self.assertNotIn("SUPPORT_THREAD_ID", live)
        self.assertNotIn("REVIEWS_CHANNEL_ID", live)


class TestGate11RunnerReadsCanon(unittest.TestCase):
    def test_legacy_audit_alias_is_fallback_only(self) -> None:
        import importlib.util

        path = os.path.join(os.path.dirname(__file__), "..", "examples", "run_complete_chassis.py")
        spec = importlib.util.spec_from_file_location("run_complete_chassis_gate11", os.path.abspath(path))
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        prefer_canon = runner.build_config(
            {"AUDIT_CHAT_ID": "-200", "CHASSIS_AUDIT_CHAT_ID": "-300"}
        )
        self.assertEqual(prefer_canon.audit_chat_id, -200)
        fallback = runner.build_config({"CHASSIS_AUDIT_CHAT_ID": "-300"})
        self.assertEqual(fallback.audit_chat_id, -300)


if __name__ == "__main__":
    unittest.main()
