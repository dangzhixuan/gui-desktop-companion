import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import Config


VALID_CONFIG = """
[persona]
choice = "温柔陪伴"
name = "小晷"
address = "你"

[schedule]
morning = "08:30"
noon = "12:30"
evening_greeting = "21:00"
summary = "22:00"
quote_interval_minutes = 90

[llm]
provider = "deepseek"
model = "deepseek-chat"
api_key = ""
base_url = "https://api.deepseek.com"
"""


class ConfigTests(unittest.TestCase):
    def _write_config(self, content=VALID_CONFIG):
        temp_dir = tempfile.TemporaryDirectory()
        path = Path(temp_dir.name) / "config.toml"
        path.write_text(content, encoding="utf-8")
        self.addCleanup(temp_dir.cleanup)
        return path

    def test_environment_api_key_takes_priority(self):
        path = self._write_config()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret-from-env"}):
            cfg = Config(path)
            self.assertTrue(cfg.has_api_key)
            self.assertEqual(cfg.llm["api_key"], "secret-from-env")

    def test_file_api_key_is_used_when_environment_is_missing(self):
        path = self._write_config(
            VALID_CONFIG.replace('api_key = ""', 'api_key = "secret-from-file"')
        )
        with patch.dict(os.environ, {}, clear=True):
            cfg = Config(path)
            self.assertTrue(cfg.has_api_key)
            self.assertEqual(cfg.llm["api_key"], "secret-from-file")

    def test_invalid_schedule_time_is_rejected(self):
        path = self._write_config(VALID_CONFIG.replace('morning = "08:30"', 'morning = "25:90"'))
        with self.assertRaisesRegex(ValueError, "不是合法"):
            Config(path)

    def test_user_settings_are_saved_and_can_be_reloaded(self):
        path = self._write_config(
            VALID_CONFIG.replace('api_key = ""', 'api_key = "keep-this-key"')
        )
        cfg = Config(path)
        cfg.save_user_settings(
            persona_choice="严师",
            persona_name='晷"先生',
            address="同学",
            schedule={
                "morning": "07:45",
                "noon": "12:10",
                "evening_greeting": "21:30",
                "summary": "22:15",
                "quote_interval_minutes": 120,
            },
        )

        reloaded = Config(path)
        self.assertEqual(reloaded.persona_choice, "严师")
        self.assertEqual(reloaded.persona_name, '晷"先生')
        self.assertEqual(reloaded.address, "同学")
        self.assertEqual(reloaded.schedule["summary"], "22:15")
        self.assertEqual(reloaded.schedule["quote_interval_minutes"], 120)
        self.assertEqual(reloaded.llm["api_key"], "keep-this-key")
        self.assertTrue(reloaded.ai_enabled)


if __name__ == "__main__":
    unittest.main()
