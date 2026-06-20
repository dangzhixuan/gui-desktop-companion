import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from core.db import DB, SCHEMA_VERSION


class DBTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "companion.db"
        self.db = DB(self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_schema_is_at_latest_version(self):
        version = self.db.conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, SCHEMA_VERSION)

    def test_review_query_keeps_tasks_completed_during_the_day(self):
        today = date.today().isoformat()
        task_id = self.db.add_task("读论文", due_date=today, priority=2)
        self.db.complete_task(task_id)

        tasks = self.db.get_tasks_for_review(today)

        self.assertEqual([row["id"] for row in tasks], [task_id])
        self.assertEqual(tasks[0]["status"], "done")

    def test_dropped_task_has_timestamp_and_review_reason(self):
        task_id = self.db.add_task("不再需要的任务")
        self.db.drop_task(task_id)
        self.db.save_task_review(task_id, "dropped", "需求已经取消")

        task = self.db.get_tasks("dropped")[0]
        review = self.db.get_task_reviews()[0]

        self.assertIsNotNone(task["dropped_at"])
        self.assertEqual(review["status"], "dropped")
        self.assertEqual(review["reason"], "需求已经取消")

    def test_task_review_upsert_does_not_duplicate(self):
        task_id = self.db.add_task("写总结")
        self.db.save_task_review(task_id, "pending", "忘了")
        self.db.save_task_review(task_id, "done")

        reviews = self.db.get_task_reviews()

        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["status"], "done")
        self.assertEqual(reviews[0]["reason"], "忘了")

    def test_saving_completed_review_does_not_rewrite_completion_time(self):
        task_id = self.db.add_task("保持完成时间")
        self.db.complete_task(task_id)
        completed_at = self.db.get_task(task_id)["completed_at"]

        from brain.agent import save_review_inputs

        save_review_inputs(
            self.db,
            [{"task_id": task_id, "status": "done", "reason": ""}],
            "总结",
            "",
            "",
        )

        self.assertEqual(self.db.get_task(task_id)["completed_at"], completed_at)

    def test_completed_task_can_be_reopened(self):
        task_id = self.db.add_task("误勾选的任务")
        self.db.complete_task(task_id)

        self.db.reopen_task(task_id)

        task = self.db.get_task(task_id)
        self.assertEqual(task["status"], "pending")
        self.assertIsNone(task["completed_at"])

    def test_task_outcome_summary_counts_pending_and_done(self):
        today = date.today().isoformat()
        done_id = self.db.add_task("已完成", due_date=today)
        self.db.add_task("未完成", due_date=today)
        self.db.complete_task(done_id)

        summary = self.db.get_task_outcome_summary(today)

        self.assertEqual(summary["total"], 2)
        self.assertEqual(summary["done"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["pending_titles"], ["未完成"])

    def test_future_scheduled_task_is_hidden_until_its_date(self):
        today = date.today()
        tomorrow = (today + timedelta(days=1)).isoformat()
        task_id = self.db.add_task(
            "明天读论文",
            scheduled_date=tomorrow,
        )

        self.assertEqual(self.db.get_today_tasks(today.isoformat()), [])
        self.assertEqual(
            [task["id"] for task in self.db.get_today_tasks(tomorrow)],
            [task_id],
        )

    def test_review_streak_allows_today_to_be_unfinished(self):
        today = date.today()
        for days_ago in (3, 2, 1):
            self.db.save_daily_log(
                summary=f"第 {days_ago} 天",
                log_date=(today - timedelta(days=days_ago)).isoformat(),
            )

        self.assertEqual(self.db.get_review_streak(), 3)

        self.db.save_daily_log(summary="今天也写了")
        self.assertEqual(self.db.get_review_streak(), 4)

    def test_review_streak_breaks_after_missing_yesterday(self):
        two_days_ago = (date.today() - timedelta(days=2)).isoformat()
        self.db.save_daily_log(summary="较早的总结", log_date=two_days_ago)

        self.assertEqual(self.db.get_review_streak(), 0)

    def test_yesterday_plan_is_returned(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.db.save_daily_log(
            summary="昨天的总结",
            plan_next="- 上午完成论文\n- 下午整理数据",
            log_date=yesterday,
        )

        self.assertEqual(
            self.db.get_yesterday_plan(),
            "- 上午完成论文\n- 下午整理数据",
        )


class LegacyMigrationTests(unittest.TestCase):
    def test_legacy_database_is_migrated_without_losing_tasks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.db"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    detail TEXT,
                    source TEXT,
                    due_date TEXT,
                    priority INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE daily_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_date TEXT NOT NULL UNIQUE,
                    summary TEXT,
                    reflection TEXT,
                    mood TEXT,
                    plan_next TEXT,
                    created_at TEXT NOT NULL
                );
                INSERT INTO tasks (title, created_at) VALUES ('旧任务', '2026-01-01 08:00:00');
                """
            )
            conn.commit()
            conn.close()

            db = DB(path)
            try:
                columns = {
                    row["name"]
                    for row in db.conn.execute("PRAGMA table_info(tasks)").fetchall()
                }
                self.assertIn("dropped_at", columns)
                self.assertIn("scheduled_date", columns)
                self.assertEqual(db.get_tasks()[0]["title"], "旧任务")
                self.assertEqual(
                    db.get_tasks()[0]["scheduled_date"],
                    "2026-01-01",
                )
                self.assertEqual(
                    db.conn.execute("PRAGMA user_version").fetchone()[0],
                    SCHEMA_VERSION,
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
