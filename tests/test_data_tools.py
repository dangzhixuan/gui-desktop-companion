import tempfile
import unittest
from pathlib import Path

from core.data_export import export_reviews_markdown
from core.db import DB
from core.startup import is_startup_enabled, set_startup_enabled, startup_file


class DataToolsTests(unittest.TestCase):
    def test_database_backup_contains_current_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = DB(root / "source.db")
            db.add_task("备份这项任务")
            backup = root / "backup.db"
            db.backup_to(backup)
            db.close()

            restored = DB(backup)
            try:
                self.assertEqual(
                    restored.get_tasks(None)[0]["title"],
                    "备份这项任务",
                )
            finally:
                restored.close()

    def test_markdown_export_contains_reviews_and_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db = DB(root / "source.db")
            task_id = db.add_task("读论文")
            db.complete_task(task_id)
            db.save_task_review(task_id, "done")
            db.save_daily_log(
                summary="完成阅读并整理笔记。",
                plan_next="- 明天继续整理数据",
            )
            target = export_reviews_markdown(db, root / "reviews.md")
            db.close()

            text = target.read_text(encoding="utf-8")
            self.assertIn("[已完成] 读论文", text)
            self.assertIn("完成阅读并整理笔记", text)
            self.assertIn("明天继续整理数据", text)

    def test_startup_file_can_be_enabled_and_disabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            startup_dir = Path(temp_dir)
            set_startup_enabled(
                True,
                startup_dir=startup_dir,
                app_path=startup_dir / "Gnomon.exe",
            )

            self.assertTrue(is_startup_enabled(startup_dir))
            self.assertIn(
                "Gnomon.exe",
                startup_file(startup_dir).read_text(encoding="utf-8"),
            )

            set_startup_enabled(False, startup_dir=startup_dir)
            self.assertFalse(is_startup_enabled(startup_dir))
