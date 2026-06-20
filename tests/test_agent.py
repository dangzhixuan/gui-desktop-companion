import json
import tempfile
import unittest
from collections import deque
from datetime import date, timedelta
from pathlib import Path

from brain.agent import (
    _normalize_review_result,
    analyze_today_tasks,
    build_pending_task_reminder,
    get_accountability_context,
    run_evening_review,
)
from core.config import Config
from core.db import DB


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DB(Path(self.temp_dir.name) / "test.db")
        config_path = Path(self.temp_dir.name) / "config.toml"
        config_path.write_text(
            """
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
""",
            encoding="utf-8",
        )
        self.cfg = Config(config_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_pending_task_reminder_names_every_task(self):
        self.cfg._data["persona"]["choice"] = "毒舌挚友"
        message = build_pending_task_reminder(
            [{"title": "读论文"}, {"title": "整理数据"}],
            self.cfg,
        )

        self.assertIn("《读论文》", message)
        self.assertIn("《整理数据》", message)
        self.assertIn("怎么还不去做《读论文》", message)
        self.assertNotIn("2 项", message)

    def test_evening_review_persists_task_reason_and_plan(self):
        self.db.add_task("读论文", due_date=date.today().isoformat())
        answers = deque(["n", "下午被临时会议打断", "整理了资料", "应提前预留时间", "一般"])

        result = run_evening_review(
            self.db,
            self.cfg,
            input_fn=lambda _prompt: answers.popleft(),
            output_fn=lambda _text: None,
            chat_fn=lambda *_args, **_kwargs: json.dumps(
                {"comment": "今天仍有推进。", "plan": ["上午读完论文"]}
            ),
        )

        review = self.db.get_task_reviews()[0]
        log = self.db.get_daily_log()
        self.assertEqual(review["status"], "pending")
        self.assertEqual(review["reason"], "下午被临时会议打断")
        self.assertEqual(log["plan_next"], "- 上午读完论文")
        self.assertEqual(result["plan"], ["上午读完论文"])

    def test_model_output_is_normalized(self):
        raw = '{"comment": 123, "plan": [" 任务一 ", 9, "", "任务二"]}'
        self.assertEqual(
            _normalize_review_result(raw),
            {"comment": "123", "plan": ["任务一", "任务二"]},
        )

    def test_invalid_model_json_falls_back_without_crashing(self):
        self.assertEqual(
            _normalize_review_result("模型暂时没有返回 JSON"),
            {"comment": "模型暂时没有返回 JSON", "plan": []},
        )

    def test_accountability_context_contains_streak_and_yesterday_plan(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.db.save_daily_log(
            summary="完成了一次复盘",
            plan_next="- 明早先读论文",
            log_date=yesterday,
        )

        self.assertEqual(
            get_accountability_context(self.db),
            {"streak": 1, "yesterday_plan": "- 明早先读论文"},
        )

    def test_task_analysis_uses_task_only_prompt(self):
        captured = {}

        def fake_chat(messages, **_kwargs):
            captured["prompt"] = messages[-1]["content"]
            return "建议先读论文，再整理数据。"

        result = analyze_today_tasks(
            ["读论文", "整理数据"],
            self.cfg,
            chat_fn=fake_chat,
        )

        self.assertEqual(result, "建议先读论文，再整理数据。")
        self.assertIn("读论文", captured["prompt"])
        self.assertIn("不询问心情", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
