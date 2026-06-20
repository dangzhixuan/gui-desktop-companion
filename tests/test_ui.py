import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSize, QTime, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QGroupBox

from core.config import Config
from core.db import DB
from core.time_context import get_business_date, get_time_context
from ui.main_window import MainWindow


CONFIG_TEXT = """
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


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        config_path = root / "config.toml"
        config_path.write_text(CONFIG_TEXT, encoding="utf-8")
        self.db = DB(root / "test.db")
        self.window = MainWindow(
            self.db,
            Config(config_path),
            startup_dir=root / "startup",
        )
        self.window.character_window.expand()

    def tearDown(self):
        self.window._quit_requested = True
        self.window.close()
        self.temp_dir.cleanup()

    def test_task_page_only_shows_completion_and_content(self):
        self.db.add_task("完成 GUI 冒烟测试", source="不应显示")
        self.window.refresh_tasks()

        self.assertEqual(self.window.task_table.columnCount(), 2)
        self.assertEqual(self.window.task_table.rowCount(), 1)
        self.assertEqual(self.window.task_table.item(0, 1).text(), "完成 GUI 冒烟测试")

    def test_review_page_summarizes_due_task(self):
        self.db.add_task("今晚复盘", due_date="2020-01-01")

        self.window.refresh_review()

        self.assertIn("1 项未完成", self.window.review_task_status.text())

    def test_summary_reminder_prepares_review_without_opening_manager(self):
        self.window.tabs.setCurrentIndex(0)
        self.window.hide()

        self.window._scheduled_summary()

        self.assertEqual(self.window.tabs.currentIndex(), 0)
        self.assertIn("还没有填写", self.window.review_status.text())
        self.assertFalse(self.window.isVisible())
        self.assertEqual(self.window.character_window.emotion, "angry")

    def test_accountability_is_visible_in_header(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.db.save_daily_log(
            summary="昨天复盘了",
            plan_next="- 今天完成实验记录",
            log_date=yesterday,
        )

        self.window.refresh_accountability()

        self.assertEqual(self.window.streak_label.text(), "连续复盘 1 天")

    def test_settings_only_expose_summary_and_task_interval(self):
        self.assertTrue(hasattr(self.window, "summary_time"))
        self.assertFalse(hasattr(self.window, "schedule_edits"))

    def test_saved_identity_and_reminder_settings_apply_immediately(self):
        self.window.persona_choice.setCurrentText("严师")
        self.window.persona_name.setText("新角色")
        self.window.persona_address.setText("同学")
        self.window.summary_time.setTime(QTime(23, 17))
        self.window.quote_interval.setValue(45)

        self.window.save_settings()

        self.assertEqual(self.window.cfg.persona_choice, "严师")
        self.assertEqual(self.window.cfg.persona_name, "新角色")
        self.assertEqual(self.window.cfg.address, "同学")
        self.assertEqual(self.window.cfg.schedule["summary"], "23:17")
        self.assertEqual(
            self.window.cfg.schedule["quote_interval_minutes"], 45
        )
        self.assertEqual(self.window.character_window.windowTitle(), "新角色")
        self.assertIn("同学", self.window.tray_icon.toolTip())
        summary_job = self.window.scheduler.scheduler.get_job("evening_summary")
        reminder_job = self.window.scheduler.scheduler.get_job("task_reminder")
        self.assertEqual(str(summary_job.trigger), "cron[hour='23', minute='17']")
        self.assertIn("0:45:00", str(reminder_job.trigger))

    def test_character_click_shows_literary_quote(self):
        self.window._show_literary_quote()

        message = "".join(self.window.character_window._message_pages)
        self.assertIn("——", message)
        self.assertEqual(
            self.window.character_window.action_button.text(), "我记住了"
        )

    def test_literary_quotes_do_not_repeat_within_one_cycle(self):
        from ui.main_window import LITERARY_QUOTES

        shown = [
            self.window._next_literary_quote()
            for _ in range(len(LITERARY_QUOTES))
        ]

        self.assertEqual(len(set(shown)), len(LITERARY_QUOTES))

    def test_note_title_shows_today_date(self):
        self.window._show_task_note()

        self.assertIn(date.today().strftime("%Y.%m.%d"), self.window.task_note.date_label.text())

    def test_pressing_enter_stages_task_until_save(self):
        self.window._run_background = (
            lambda _fn, on_success, _on_error: on_success("任务已保存。")
        )
        note = self.window.task_note
        self.window._show_task_note()
        note.editor.setText("阅读论文一篇")

        note.editor.returnPressed.emit()

        self.assertEqual(note._draft_titles, ["阅读论文一篇"])
        self.assertEqual(self.db.get_today_tasks(), [])
        draft_texts = [
            note.task_layout.itemAt(index).widget().text()
            for index in range(note.task_layout.count() - 1)
            if isinstance(note.task_layout.itemAt(index).widget(), QCheckBox)
        ]
        self.assertIn("阅读论文一篇  （待保存）", draft_texts)

        note._save()

        self.assertEqual(
            [task["title"] for task in self.db.get_today_tasks()],
            ["阅读论文一篇"],
        )
        self.assertTrue(note.isVisible())
        self.assertIn(
            "阅读论文一篇",
            [
                note.task_layout.itemAt(index).widget().text()
                for index in range(note.task_layout.count() - 1)
                if isinstance(note.task_layout.itemAt(index).widget(), QCheckBox)
            ],
        )

    def test_windows_have_practical_resize_bounds(self):
        note = self.window.task_note

        self.assertEqual(
            note._resize_edges_at(QPoint(1, 1)),
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
        )
        self.assertEqual(
            note._resize_edges_at(
                QPoint(note.width() - 1, note.height() - 1)
            ),
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
        )
        self.assertEqual(note.minimumSize(), QSize(280, 220))
        self.assertEqual(self.window.minimumSize(), QSize(680, 500))

    def test_settings_page_scrolls_instead_of_clipping_groups(self):
        self.window.resize(700, 500)
        self.window.tabs.setCurrentIndex(4)
        self.window.show()
        self.app.processEvents()

        groups = self.window.settings_scroll.widget().findChildren(QGroupBox)

        self.assertTrue(self.window.settings_scroll.widgetResizable())
        self.assertGreater(
            self.window.settings_scroll.verticalScrollBar().maximum(),
            0,
        )
        self.assertTrue(groups)
        self.assertTrue(
            all(group.height() >= group.minimumSizeHint().height() for group in groups)
        )

    def test_character_emotion_changes_for_review_and_response(self):
        self.window.character_window.RESPONSE_TIMEOUT_MS = 1

        self.window.character_window.ask_for_review("任务完成了吗？")
        self.assertEqual(self.window.character_window.emotion, "serious")

        self.window.character_window._become_angry_if_waiting()
        self.assertEqual(self.window.character_window.emotion, "angry")

        self.window.character_window.acknowledge_response("收到。")
        self.assertEqual(self.window.character_window.emotion, "smile")

    def test_character_task_button_opens_note_not_manager(self):
        self.window.character_window.ask_for_tasks()
        self.window.hide()

        self.window._handle_character_action("tasks")

        self.assertTrue(self.window.task_note.isVisible())
        self.assertFalse(self.window.isVisible())

    def test_no_task_greeting_shows_task_button_immediately(self):
        self.window._show_greeting("晚上好，今天辛苦了。")

        self.assertFalse(
            self.window.character_window.continue_button.isVisible()
        )
        self.assertTrue(self.window.character_window.action_button.isVisible())
        self.assertEqual(
            self.window.character_window.action_button.text(),
            "我这就写规划",
        )

    def test_late_night_prioritizes_review_before_sleep(self):
        task_id = self.db.add_task("完成昨晚的论文")
        self.db.conn.execute(
            "UPDATE tasks SET created_at = ? WHERE id = ?",
            ("2026-06-19 20:00:00", task_id),
        )
        self.db.conn.commit()

        self.window.load_greeting(
            now=datetime(2026, 6, 20, 0, 48), force=True
        )

        message = "".join(self.window.character_window._message_pages)
        self.assertIn("没有记录就没有进步", message)
        self.assertEqual(
            self.window.character_window._pending_action,
            ("我这就写总结", "review"),
        )

    def test_late_night_urges_sleep_after_review_is_written(self):
        self.db.save_daily_log(
            summary="今天已经完成复盘",
            log_date="2026-06-19",
        )

        state = self.window._evaluate_supervision(
            now=datetime(2026, 6, 20, 1, 0)
        )

        message = "".join(self.window.character_window._message_pages)
        self.assertEqual(state, "sleep")
        self.assertIn("黑眼圈", message)
        self.assertEqual(
            self.window.character_window._pending_action,
            ("我这就滚去睡觉", "sleep"),
        )

    def test_dismissing_quote_immediately_restores_review_warning(self):
        self.window._now_provider = lambda: datetime(2026, 6, 20, 1, 0)
        self.window._show_literary_quote()

        self.window.character_window._emit_action()
        self.app.processEvents()

        message = "".join(self.window.character_window._message_pages)
        self.assertIn("没有记录就没有进步", message)
        self.assertEqual(
            self.window.character_window._pending_action,
            ("我这就写总结", "review"),
        )

    def test_new_day_without_tasks_offers_today_note(self):
        self.window.load_greeting(
            now=datetime(2026, 6, 20, 8, 0), force=True
        )

        message = "".join(self.window.character_window._message_pages)
        self.assertIn("你今天还没有写任务呢", message)
        self.assertIn("我来监督你吧", message)
        self.assertEqual(
            self.window.character_window.action_button.text(), "我这就写规划"
        )

    def test_task_reminder_has_no_button_when_tasks_exist(self):
        self.db.add_task("读论文", due_date=date.today().isoformat())
        self.db.add_task("整理数据", due_date=date.today().isoformat())
        self.window._now_provider = lambda: datetime.combine(
            date.today(), datetime.min.time()
        ).replace(hour=8)

        original = self.window.cfg._data["schedule"]
        self.window.cfg._data["schedule"] = dict(original)
        self.window.cfg._data["schedule"]["morning"] = "00:00"
        self.window.cfg._data["schedule"]["summary"] = "23:59"
        try:
            self.window._scheduled_task_reminder()
        finally:
            self.window.cfg._data["schedule"] = original

        message = "".join(self.window.character_window._message_pages)
        self.assertIn("读论文", message)
        self.assertIn("整理数据", message)
        self.assertNotIn("2 项任务", message)
        self.assertEqual(
            self.window.character_window._pending_action,
            ("我这就滚去学习", "study"),
        )

    def test_summary_and_reflection_use_one_input_and_save_together(self):
        self.window._run_background = (
            lambda fn, on_success, _on_error: on_success(
                {"comment": "今天有拖延，明天别再磨蹭。", "plan": ["先读论文"]}
            )
        )
        self.window.review_summary.setPlainText("完成了资料整理，但下午拖延了。")

        self.window.submit_review()

        log = self.db.get_daily_log(get_business_date().isoformat())
        self.assertEqual(log["summary"], "完成了资料整理，但下午拖延了。")
        self.assertFalse(log["reflection"])
        self.assertFalse(log["mood"])
        self.assertIn("今天有拖延", self.window.review_result.toPlainText())

    def test_ai_disabled_saves_review_without_background_request(self):
        self.window.cfg._data["llm"]["enabled"] = False
        self.window._apply_ai_state()
        self.window._run_background = lambda *_args: self.fail(
            "AI 关闭时不应启动后台请求"
        )
        self.window.review_summary.setPlainText("只保存在本地。")

        self.window.submit_review()

        log = self.db.get_daily_log(get_business_date().isoformat())
        self.assertEqual(log["summary"], "只保存在本地。")
        self.assertIn("未发送", self.window.review_result.toPlainText())

    def test_ai_and_startup_settings_are_saved(self):
        self.window.ai_enabled.setChecked(False)
        self.window.startup_enabled.setChecked(True)

        self.window.save_settings()

        self.assertFalse(self.window.cfg.ai_enabled)
        self.assertTrue((Path(self.temp_dir.name) / "startup").exists())
        self.assertTrue(self.window.review_button.text().startswith("保存到本地"))

    def test_advisor_draft_can_be_imported_into_note(self):
        self.window.advisor_draft.setPlainText("拆分论文提纲\n阅读第一节")

        self.window.import_advisor_tasks()

        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        self.assertEqual(
            [task["title"] for task in self.db.get_today_tasks()],
            [],
        )
        self.assertEqual(
            [task["scheduled_date"] for task in self.db.get_tasks("pending")],
            [tomorrow, tomorrow],
        )
        self.assertFalse(self.window.task_note.isVisible())

    def test_completed_task_title_can_be_added_again_on_a_new_day(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        task_id = self.db.add_task(
            "读论文",
            scheduled_date=yesterday,
        )
        self.db.complete_task(task_id)
        self.db.conn.execute(
            "UPDATE tasks SET completed_at = ? WHERE id = ?",
            (f"{yesterday} 20:00:00", task_id),
        )
        self.db.conn.commit()
        self.window._run_background = (
            lambda _fn, on_success, _on_error: on_success("今天继续。")
        )

        self.window._save_note_tasks(["读论文"])

        matching = [
            task for task in self.db.get_tasks(None)
            if task["title"] == "读论文"
        ]
        self.assertEqual(len(matching), 2)
        self.assertEqual(matching[0]["scheduled_date"], yesterday)
        self.assertEqual(matching[1]["scheduled_date"], date.today().isoformat())

    def test_closing_manager_hides_it_without_stopping_background(self):
        self.window.show()

        self.window.close()

        self.assertFalse(self.window.isVisible())
        self.assertFalse(self.window._closing)
        self.assertIsNotNone(
            self.window.scheduler.scheduler.get_job("task_reminder")
        )
        self.assertEqual(self.db.get_tasks(None), [])

    def test_same_greeting_slot_is_only_shown_once(self):
        now = datetime.combine(date.today(), datetime.min.time()).replace(hour=8)
        event = "greeting_morning"
        self.window._app_settings.remove(
            self.window._event_key(event, date.today().isoformat())
        )
        self.window.load_greeting(now=now)
        first = self.window.character_window.bubble.text()

        self.window.character_window.set_message("不应被覆盖")
        self.window.load_greeting(now=now)

        self.assertEqual(
            self.window.character_window.bubble.text(), "不应被覆盖"
        )
        self.assertNotEqual(first, "")

    def test_character_message_is_paginated_one_sentence_at_a_time(self):
        character = self.window.character_window
        character.set_message(
            "第一句话。第二句话。",
            action_label="填写任务",
            action_id="tasks",
        )

        self.assertEqual(character.bubble.text(), "第一句话。")
        self.assertTrue(character.continue_button.isVisible())
        self.assertFalse(character.action_button.isVisible())

        character.show_next_message()

        self.assertEqual(character.bubble.text(), "第二句话。")
        self.assertFalse(character.continue_button.isVisible())
        self.assertTrue(character.action_button.isVisible())

    def test_note_tasks_are_saved_and_analysis_is_shown(self):
        self.window._run_background = (
            lambda fn, on_success, _on_error: on_success("任务量适中，先完成论文。")
        )

        self.window._save_note_tasks(["读论文", "整理数据"])

        self.assertEqual(
            [task["title"] for task in self.db.get_today_tasks()],
            ["读论文", "整理数据"],
        )
        self.assertEqual(
            self.window.character_window.bubble.text(),
            "任务量适中，先完成论文。",
        )
        self.assertEqual(
            self.window.character_window.action_button.text(),
            "我这就滚去学习",
        )

    def test_sleep_commitment_button_only_closes_bubble(self):
        character = self.window.character_window
        character.urge_sleep("现在去睡觉，别再透支明天。")

        character._emit_action()

        self.assertFalse(character.bubble_card.isVisible())

    def test_study_commitment_button_only_closes_bubble(self):
        character = self.window.character_window
        character.urge_study("时间不多了，现在去学习。")

        character._emit_action()

        self.assertFalse(character.bubble_card.isVisible())

    def test_plan_commitment_button_opens_today_note(self):
        character = self.window.character_window
        character.ask_for_tasks("先把今天的规划写下来。")

        character._emit_action()

        self.assertTrue(self.window.task_note.isVisible())

    def test_note_checkbox_is_the_only_way_to_complete_task(self):
        task_id = self.db.add_task("读论文", source="今日便签")
        self.window._show_task_note()

        self.assertEqual(self.db.get_task(task_id)["status"], "pending")

    def test_note_checkbox_changes_do_not_trigger_character_reply(self):
        task_id = self.db.add_task("安静更新状态", source="今日便签")
        before = self.window.character_window.bubble.text()

        self.window._toggle_note_task(task_id, True)

        self.assertEqual(self.window.character_window.bubble.text(), before)

        self.window._toggle_note_task(task_id, True)

        self.assertEqual(self.db.get_task(task_id)["status"], "done")

        self.window._toggle_note_task(task_id, False)

        self.assertEqual(self.db.get_task(task_id)["status"], "pending")

    def test_greeting_never_claims_pending_tasks_are_complete(self):
        self.db.add_task("读论文", source="今日便签")
        event = f"greeting_{get_time_context().slot}"
        self.window._app_settings.remove(self.window._event_key(event))

        self.window.load_greeting(
            now=datetime.combine(date.today(), datetime.min.time()).replace(
                hour=8
            ),
            force=True,
        )

        text = "".join(self.window.character_window._message_pages)
        self.assertIn("读论文", text)
        self.assertNotIn("全部完成", text)

    def test_dismiss_action_hides_bubble(self):
        character = self.window.character_window
        character.show_full_message("完整建议")

        character._emit_action()

        self.assertFalse(character.bubble_card.isVisible())

    def test_character_can_collapse_and_restore(self):
        character = self.window.character_window
        expanded_size = character.size()

        character.collapse()

        self.assertTrue(character.is_collapsed)
        self.assertEqual(character.size(), character.COLLAPSED_SIZE)
        self.assertTrue(character.launcher_button.isVisible())
        self.assertEqual(character.launcher_button.text(), "晷")
        self.assertGreater(character.launcher_button.width(), 0)
        self.assertGreater(character.launcher_button.height(), 0)

        character.expand()

        self.assertFalse(character.is_collapsed)
        self.assertEqual(character.size(), expanded_size)
        self.assertTrue(character.character.isVisible())

    def test_collapsed_launcher_can_be_dragged_without_expanding(self):
        character = self.window.character_window
        character.collapse()
        start = character.pos()
        press = character.frameGeometry().topLeft() + QPoint(20, 20)

        character._begin_drag(press)
        character._continue_drag(press + QPoint(80, 45))
        character._finish_drag()

        self.assertTrue(character.is_collapsed)
        self.assertEqual(character.pos(), start + QPoint(80, 45))
        self.assertEqual(
            character._settings.value("character_collapsed_position"),
            character.pos(),
        )

    def test_clicking_collapsed_launcher_expands_character(self):
        character = self.window.character_window
        character.collapse()
        press = character.frameGeometry().topLeft() + QPoint(20, 20)

        character._begin_drag(press)
        character._finish_drag()

        self.assertFalse(character.is_collapsed)

    def test_character_size_can_be_changed_and_restored_after_collapse(self):
        character = self.window.character_window
        character.resize(360, 540)

        character.collapse()
        character.expand()

        self.assertEqual(character.size(), QSize(360, 540))

    def test_summary_reminder_does_not_open_manager(self):
        self.window.hide()

        self.window._scheduled_summary()

        self.assertFalse(self.window.isVisible())
        self.assertEqual(self.window.character_window.emotion, "angry")
        self.assertIn("没有记录就没有进步", "".join(
            self.window.character_window._message_pages
        ))


if __name__ == "__main__":
    unittest.main()
