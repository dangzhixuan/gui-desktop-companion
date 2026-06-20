from datetime import date, datetime, timedelta
import hashlib
import random

from PySide6.QtCore import QSettings, QTime, QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
    QStyle,
    QSystemTrayIcon,
)

from brain import agent
from core.config import Config, VALID_PERSONAS
from core.data_export import export_reviews_markdown
from core.db import DB
from core.scheduler import CompanionScheduler
from core.startup import is_startup_enabled, set_startup_enabled
from core.time_context import get_business_date, get_time_context
from ui.character_window import CharacterWindow
from ui.reminders import ReminderBridge
from ui.task_note import TaskNoteWindow
from ui.workers import FunctionWorker


STATUS_TEXT = {"pending": "未完成", "done": "已完成", "dropped": "已放弃"}
REVIEW_REMINDER = (
    "每天都要记录，不然今天吃过的亏明天还会再吃一次。"
    "时间真的不多了，你想成为配得上喜欢的人、让别人尊重的人，"
    "就不能连自己的成长都不留下证据。没有记录就没有进步，快去写总结与反思。"
)
LITERARY_QUOTES = (
    "“人是自由的，人注定自由，人背负着自由的重量。”\n"
    "——萨特《存在与虚无》",
    "“一个人知道自己为什么而活，就可以忍受任何一种生活。”\n"
    "——尼采",
    "“世界上只有一种真正的英雄主义，就是认清生活的真相后依然热爱生活。”\n"
    "——罗曼·罗兰",
    "“生活不可能像你想象得那么好，但也不会像你想象得那么糟。”\n"
    "——莫泊桑《一生》",
    "“黑夜无论怎样悠长，白昼总会到来。”\n"
    "——莎士比亚《麦克白》",
    "“未经审视的人生不值得过。”\n"
    "——苏格拉底",
    "“我们听到的一切都是一个观点，不是事实；我们看见的一切都是一个视角，不是真相。”\n"
    "——马可·奥勒留《沉思录》",
    "“真正的发现之旅，不在于寻找新的风景，而在于拥有新的眼睛。”\n"
    "——普鲁斯特",
)


class MainWindow(QMainWindow):
    def __init__(self, db=None, cfg=None, *, startup_dir=None):
        super().__init__()
        self.db = db or DB()
        self.cfg = cfg or Config()
        self._startup_dir = startup_dir
        self._workers = set()
        self._closing = False
        self._quit_requested = False
        self._refreshing_tasks = False
        self._now_provider = datetime.now
        self._supervision_retry_timer = QTimer(self)
        self._supervision_retry_timer.setSingleShot(True)
        self._supervision_retry_timer.timeout.connect(
            self._evaluate_supervision
        )
        self._app_settings = QSettings("Gnomon", "DesktopCompanion")
        self._profile_id = hashlib.sha1(
            str(self.db.db_path).encode("utf-8")
        ).hexdigest()[:12]

        self.setWindowTitle("晷 · 管理中心")
        self.resize(820, 610)
        self.setMinimumSize(680, 500)
        self._build_ui()
        self._apply_style()
        self._setup_character()
        self._setup_reminders()
        self.refresh_all()
        self.load_greeting(force=True)
        QTimer.singleShot(1000, self._check_missing_review)

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title_row = QHBoxLayout()
        title = QLabel("管理中心")
        title.setObjectName("appTitle")
        title_row.addWidget(title)
        subtitle = QLabel("任务、复盘与规划")
        subtitle.setObjectName("subtitle")
        title_row.addWidget(subtitle)
        title_row.addStretch()
        self.streak_label = QLabel("连续复盘 0 天")
        self.streak_label.setObjectName("streakBadge")
        title_row.addWidget(self.streak_label)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh_all)
        title_row.addWidget(refresh)
        layout.addLayout(title_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tasks_tab(), "每日任务")
        self.tabs.addTab(self._build_review_tab(), "总结与反思")
        self.tabs.addTab(self._build_advisor_tab(), "任务顾问")
        self.tabs.addTab(self._build_history_tab(), "历史")
        self.tabs.addTab(self._build_settings_tab(), "设置")
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("任务数据与今日便签实时同步")

    def _build_tasks_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        text = QLabel("这里只显示任务内容和完成情况；新增任务请直接写在今日便签。")
        text.setWordWrap(True)
        row.addWidget(text, 1)
        button = QPushButton("打开今日便签")
        button.setObjectName("primaryButton")
        button.clicked.connect(self._show_task_note)
        row.addWidget(button)
        layout.addLayout(row)

        self.task_table = QTableWidget(0, 2)
        self.task_table.setHorizontalHeaderLabels(["完成情况", "任务内容"])
        self.task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.task_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.task_table, 1)
        return page

    def _build_review_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "总结与反思是同一份记录。写下完成情况、拖延原因、收获和明天的改进即可。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.review_task_status = QLabel()
        self.review_task_status.setWordWrap(True)
        self.review_task_status.setObjectName("infoCard")
        layout.addWidget(self.review_task_status)

        box = QGroupBox("今日总结与反思")
        box_layout = QVBoxLayout(box)
        self.review_summary = QTextEdit()
        self.review_summary.setPlaceholderText(
            "例如：今天完成了什么？哪里偷懒或拖延了？为什么？明天怎样改进？"
        )
        self.review_summary.setMinimumHeight(180)
        box_layout.addWidget(self.review_summary)
        layout.addWidget(box)

        action_row = QHBoxLayout()
        self.review_status = QLabel()
        self.review_status.setWordWrap(True)
        action_row.addWidget(self.review_status, 1)
        self.review_button = QPushButton("保存并获取反馈")
        self.review_button.setObjectName("primaryButton")
        self.review_button.clicked.connect(self.submit_review)
        action_row.addWidget(self.review_button)
        layout.addLayout(action_row)

        self.review_result = QTextEdit()
        self.review_result.setReadOnly(True)
        self.review_result.setPlaceholderText("保存后，角色对今日表现的分析会显示在这里。")
        self.review_result.setMinimumHeight(140)
        layout.addWidget(self.review_result)
        return page

    def _build_advisor_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel(
            "任务顾问会检查长期未完成和反复拖延的任务，把复杂任务拆成可执行的明日清单。"
            "清单可以直接修改，确认后安排到明日。"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.advisor_button = QPushButton("一键生成明日任务")
        self.advisor_button.setObjectName("primaryButton")
        self.advisor_button.clicked.connect(self.generate_advisor_plan)
        layout.addWidget(self.advisor_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self.advisor_analysis = QLabel("尚未分析。")
        self.advisor_analysis.setWordWrap(True)
        self.advisor_analysis.setObjectName("infoCard")
        layout.addWidget(self.advisor_analysis)

        self.advisor_draft = QTextEdit()
        self.advisor_draft.setPlaceholderText("生成后会在这里显示，一行一项，可自行修改。")
        layout.addWidget(self.advisor_draft, 1)

        button = QPushButton("安排到明日")
        button.setObjectName("primaryButton")
        button.clicked.connect(self.import_advisor_tasks)
        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignRight)
        return page

    def _build_history_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        splitter = QSplitter()
        self.history_dates = QListWidget()
        self.history_dates.currentTextChanged.connect(self.show_history_date)
        self.history_detail = QTextEdit()
        self.history_detail.setReadOnly(True)
        splitter.addWidget(self.history_dates)
        splitter.addWidget(self.history_detail)
        splitter.setSizes([190, 570])
        layout.addWidget(splitter)
        return page

    def _build_settings_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        persona_box = QGroupBox("人格与称呼")
        persona_form = QFormLayout(persona_box)
        self.persona_choice = QComboBox()
        self.persona_choice.addItems(VALID_PERSONAS)
        self.persona_name = QLineEdit()
        self.persona_address = QLineEdit()
        persona_form.addRow("人格", self.persona_choice)
        persona_form.addRow("角色名字", self.persona_name)
        persona_form.addRow("如何称呼你", self.persona_address)
        layout.addWidget(persona_box)

        schedule_box = QGroupBox("提醒时间")
        schedule_form = QFormLayout(schedule_box)
        self.summary_time = QTimeEdit()
        self.summary_time.setDisplayFormat("HH:mm")
        schedule_form.addRow("总结检查", self.summary_time)
        self.quote_interval = QSpinBox()
        self.quote_interval.setRange(15, 1440)
        self.quote_interval.setSuffix(" 分钟")
        schedule_form.addRow("任务提醒间隔", self.quote_interval)
        layout.addWidget(schedule_box)

        privacy_box = QGroupBox("隐私与 AI")
        privacy_layout = QVBoxLayout(privacy_box)
        self.ai_enabled = QCheckBox("启用 DeepSeek 智能分析")
        privacy_layout.addWidget(self.ai_enabled)
        privacy_notice = QLabel(
            "启用后，任务标题、近期总结与反思、任务完成情况会发送给 DeepSeek，"
            "用于生成任务建议和复盘反馈。关闭后仅使用本地提醒，数据不会发送到云端。"
        )
        privacy_notice.setWordWrap(True)
        privacy_layout.addWidget(privacy_notice)
        layout.addWidget(privacy_box)

        system_box = QGroupBox("系统")
        system_layout = QVBoxLayout(system_box)
        self.startup_enabled = QCheckBox("登录 Windows 后自动启动")
        system_layout.addWidget(self.startup_enabled)
        layout.addWidget(system_box)

        data_box = QGroupBox("数据保护")
        data_layout = QHBoxLayout(data_box)
        backup_button = QPushButton("备份数据库")
        backup_button.clicked.connect(self.backup_database)
        data_layout.addWidget(backup_button)
        export_button = QPushButton("导出复盘为 Markdown")
        export_button.clicked.connect(self.export_reviews)
        data_layout.addWidget(export_button)
        data_layout.addStretch()
        layout.addWidget(data_box)

        save = QPushButton("保存设置")
        save.setObjectName("primaryButton")
        save.clicked.connect(self.save_settings)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)
        layout.addStretch()
        return page

    def _apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f3f6f2; color: #20352a; }
            QWidget { font-size: 14px; font-family: "Microsoft YaHei UI"; }
            QLabel#appTitle { font-size: 28px; font-weight: 700; color: #173d2a; }
            QLabel#subtitle { color: #718076; margin-left: 8px; }
            QLabel#streakBadge, QLabel#infoCard {
                color: #294735; background: #dfe9df;
                border: 1px solid #c5d4c6;
                border-radius: 7px; padding: 8px 12px;
            }
            QGroupBox {
                background: #fbfcfa; border: 1px solid #ccd8ce;
                border-radius: 8px; margin-top: 12px; padding: 12px;
                font-weight: 600; color: #264b36;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QLineEdit, QTextEdit, QComboBox, QTimeEdit, QSpinBox {
                background: #ffffff; color: #20352a;
                border: 1px solid #bdcbbf;
                border-radius: 6px; padding: 6px;
                selection-background-color: #527b63;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus,
            QTimeEdit:focus, QSpinBox:focus { border: 1px solid #527b63; }
            QPushButton {
                color: #254733; background: #e1e9e1;
                border: 1px solid #c3d1c5; border-radius: 6px;
                padding: 7px 14px;
            }
            QPushButton:hover { background: #d2dfd3; border-color: #9fb3a3; }
            QPushButton:pressed { background: #c2d3c5; }
            QPushButton:disabled { color: #8e9a91; background: #edf0ed; }
            QPushButton#primaryButton {
                background: #24513b; color: #ffffff; border: 1px solid #24513b;
            }
            QPushButton#primaryButton:hover {
                background: #183d2b; border-color: #183d2b;
            }
            QTabWidget::pane {
                border: 1px solid #cbd7cd; background: #f8faf7;
                top: -1px;
            }
            QTabBar::tab {
                color: #53675a; background: #e8eee8;
                border: 1px solid #d0dbd2; padding: 9px 15px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                color: #f8faf7; background: #315d45;
                border-color: #315d45; border-radius: 6px;
            }
            QTabBar::tab:hover:!selected { background: #dbe6dc; }
            QTableWidget, QListWidget {
                background: #ffffff; alternate-background-color: #f1f5f1;
                border: 1px solid #c8d5ca;
                border-radius: 7px; gridline-color: #e2e9e3;
                selection-background-color: #d5e3d6;
                selection-color: #173d2a;
            }
            QHeaderView::section {
                color: #294735; background: #e1e9e1;
                border: 0; border-right: 1px solid #c8d5ca;
                border-bottom: 1px solid #c8d5ca; padding: 7px;
                font-weight: 600;
            }
            QCheckBox { spacing: 7px; color: #294735; }
            QStatusBar {
                color: #627269; background: #e8eee8;
                border-top: 1px solid #d0dbd2;
            }
            """
        )

    def _setup_character(self):
        self.character_window = CharacterWindow()
        self.task_note = TaskNoteWindow()
        self.character_window.activated.connect(self._show_main_window)
        self.character_window.character_clicked.connect(self._show_literary_quote)
        self.character_window.action_requested.connect(self._handle_character_action)
        self.character_window.action_finished.connect(
            self._character_action_finished
        )
        self.character_window.note_requested.connect(self._show_task_note)
        self.task_note.tasks_saved.connect(self._save_note_tasks)
        self.task_note.task_toggled.connect(self._toggle_note_task)
        self.character_window.show_near_bottom_right()
        self._apply_character_identity()

    def _show_literary_quote(self):
        self.character_window.show_full_message(
            self._next_literary_quote(),
            action_label="我记住了",
            action_id="quote_dismiss",
        )

    def _next_literary_quote(self):
        key = f"quotes/{self._profile_id}/remaining"
        raw = str(self._app_settings.value(key, "") or "")
        remaining = [
            int(value)
            for value in raw.split(",")
            if value.isdigit() and int(value) < len(LITERARY_QUOTES)
        ]
        if not remaining:
            remaining = list(range(len(LITERARY_QUOTES)))
            random.shuffle(remaining)
        index = remaining.pop(0)
        self._app_settings.setValue(key, ",".join(map(str, remaining)))
        return LITERARY_QUOTES[index]

    def _character_action_finished(self, action_id):
        if self._closing:
            return
        if action_id == "quote_dismiss":
            self._evaluate_supervision()
            return
        self._supervision_retry_timer.start(60 * 1000)

    def _apply_character_identity(self):
        self.character_window.setWindowTitle(self.cfg.persona_name)
        if hasattr(self, "tray_icon"):
            self.tray_icon.setToolTip(
                f"{self.cfg.persona_name} · {self.cfg.address}的桌面成长伙伴"
            )

    def _setup_reminders(self):
        self.reminder_bridge = ReminderBridge(self)
        self.reminder_bridge.greeting_due.connect(self._scheduled_greeting)
        self.reminder_bridge.summary_due.connect(self._scheduled_summary)
        self.reminder_bridge.task_reminder_due.connect(self._scheduled_task_reminder)
        self.scheduler = CompanionScheduler(
            self.reminder_bridge.emit_greeting,
            self.reminder_bridge.emit_summary,
            self.reminder_bridge.emit_task_reminder,
        )
        self.scheduler.start(self.cfg.schedule)

        self.review_watch_timer = QTimer(self)
        self.review_watch_timer.setInterval(2 * 60 * 1000)
        self.review_watch_timer.timeout.connect(self._evaluate_supervision)
        self.review_watch_timer.start()

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        )
        self.tray_icon.setToolTip(
            f"{self.cfg.persona_name} · {self.cfg.address}的桌面成长伙伴"
        )
        menu = QMenu(self)
        show_action = QAction("显示管理中心", self)
        show_action.triggered.connect(self._show_main_window)
        note_action = QAction("打开今日便签", self)
        note_action.triggered.connect(self._show_task_note)
        character_action = QAction("收起/展开角色", self)
        character_action.triggered.connect(self._toggle_character)
        quit_action = QAction("退出", self)
        quit_action.triggered.connect(self._quit_application)
        menu.addAction(show_action)
        menu.addAction(note_action)
        menu.addAction(character_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

    def _show_task_note(self):
        tasks = [
            {"id": task["task_id"], "title": task["title"], "status": task["status"]}
            for task in agent.prepare_evening_review(self.db)
            if task["status"] in {"pending", "done"}
        ]
        self.task_note.set_tasks(tasks)
        position = self.character_window.pos()
        self.task_note.move(
            max(0, position.x() - self.task_note.width() - 12),
            max(0, position.y() + 170),
        )
        self.task_note.show()
        self.task_note.raise_()
        self.task_note.activateWindow()

    def _handle_character_action(self, action_id):
        if action_id == "tasks":
            self._show_task_note()
            return
        if action_id == "review":
            self._show_main_window()
            self.tabs.setCurrentIndex(1)
            self.refresh_review()
            self.review_summary.setFocus()
            self.character_window.mark_engaged()

    def _toggle_note_task(self, task_id, is_done):
        task = self.db.get_task(task_id)
        if task is None:
            return
        if is_done and task["status"] != "done":
            self.db.complete_task(task_id)
            self.db.save_task_review(task_id, "done")
        elif not is_done and task["status"] != "pending":
            self.db.reopen_task(task_id)
            self.db.save_task_review(task_id, "pending", reason="")
        self.refresh_tasks()
        self.refresh_review()

    def _save_note_tasks(self, titles):
        task_date = get_business_date(self._now_provider()).isoformat()
        existing = {
            task["title"].strip()
            for task in agent.prepare_evening_review(self.db, task_date)
        }
        new_titles = [title.strip() for title in titles if title.strip() not in existing]
        for title in new_titles:
            self.db.add_task(
                title,
                source="今日便签",
                scheduled_date=task_date,
            )
        self.task_note.hide()
        self.refresh_tasks()
        self.refresh_review()
        if not new_titles:
            self.character_window.show_full_message("这些任务已经在今日便签里了。")
            return
        self.character_window.set_emotion(
            "serious", "任务记下了，我正在帮你看看安排是否合理。"
        )
        if not self.cfg.ai_enabled:
            self.character_window.urge_study(
                agent.build_pending_task_reminder(
                    self.db.get_today_tasks(task_date), self.cfg
                )
            )
            return
        self._run_background(
            lambda: agent.analyze_today_tasks(new_titles, self.cfg),
            self._show_task_analysis,
            self._task_analysis_failed,
        )

    def _show_task_analysis(self, analysis):
        self.character_window.urge_study(
            analysis
            or "任务已保存。时间不会等你，先做最重要的一项。"
            "你想追上喜欢的人、让别人看到你的实力，就得从现在的行动开始。"
        )

    def _task_analysis_failed(self, _message):
        self.character_window.urge_study(
            "任务已保存。先做最重要的一项，别再把时间送给拖延。"
            "今天少做一步，明天就会离目标和想追上的人更远一点。"
        )

    def refresh_all(self):
        self.refresh_accountability()
        self.refresh_tasks()
        self.refresh_review()
        self.refresh_history()
        self.load_settings()
        self.statusBar().showMessage("已刷新", 2500)

    def refresh_accountability(self):
        streak = self.db.get_review_streak()
        self.streak_label.setText(f"连续复盘 {streak} 天")

    def refresh_tasks(self):
        tasks = agent.prepare_evening_review(self.db)
        self._refreshing_tasks = True
        self.task_table.setRowCount(len(tasks))
        for row, task in enumerate(tasks):
            check = QCheckBox(STATUS_TEXT[task["status"]])
            check.setChecked(task["status"] == "done")
            check.setEnabled(task["status"] != "dropped")
            check.stateChanged.connect(
                lambda state, task_id=task["task_id"]: self._table_task_toggled(
                    task_id, state
                )
            )
            self.task_table.setCellWidget(row, 0, check)
            self.task_table.setItem(row, 1, QTableWidgetItem(task["title"]))
        self._refreshing_tasks = False

    def _table_task_toggled(self, task_id, state):
        if self._refreshing_tasks:
            return
        self._toggle_note_task(task_id, state == Qt.CheckState.Checked.value)
        if self.task_note.isVisible():
            self._show_task_note()

    def refresh_review(self):
        tasks = agent.prepare_evening_review(self.db)
        done = sum(task["status"] == "done" for task in tasks)
        pending = sum(task["status"] == "pending" for task in tasks)
        self.review_task_status.setText(
            f"今日任务：{done} 项已完成，{pending} 项未完成。"
            "任务状态请在便签或“每日任务”页勾选。"
        )
        log = self.db.get_daily_log()
        current = (log["summary"] if log else None) or ""
        if current and not self.review_summary.toPlainText().strip():
            self.review_summary.setPlainText(current)
        if current:
            self.review_status.setText("今天的总结与反思已保存，可以继续修改。")
        else:
            self.review_status.setText("今天还没有填写总结与反思。")

    def _collect_review_results(self, review_date=None):
        return [
            {
                "task_id": task["task_id"],
                "title": task["title"],
                "status": task["status"],
                "done": task["status"] == "done",
                "reason": "",
            }
            for task in agent.prepare_evening_review(self.db, review_date)
        ]

    def submit_review(self):
        summary = self.review_summary.toPlainText().strip()
        if not summary:
            QMessageBox.warning(
                self, "还没写呢", "请在同一个输入框中写下今天的总结与反思。"
            )
            return
        review_date = get_business_date().isoformat()
        task_results = self._collect_review_results(review_date)
        try:
            agent.save_review_inputs(
                self.db, task_results, summary, review_date=review_date
            )
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return

        self.character_window.acknowledge_response(
            "这才对嘛。记录已经保存。"
        )
        if not self.cfg.ai_enabled:
            self.review_result.setPlainText(
                "今日记录已保存在本地。AI 已关闭，未发送任何任务或复盘内容。"
            )
            self.review_status.setText("总结与反思已保存到本地。")
            self.refresh_accountability()
            self.refresh_history()
            self._evaluate_supervision()
            return
        self.review_button.setEnabled(False)
        self.review_status.setText("已保存，正在分析今日表现……")
        db_path = self.db.db_path
        config_path = self.cfg.path

        def work():
            worker_db = DB(db_path)
            try:
                return agent.generate_review_analysis(
                    worker_db,
                    Config(config_path),
                    task_results,
                    summary,
                    review_date=review_date,
                )
            finally:
                worker_db.close()

        self._run_background(work, self._show_review_result, self._review_failed)

    def _show_review_result(self, result):
        plan = "\n".join(f"{i}. {item}" for i, item in enumerate(result["plan"], 1))
        self.review_result.setPlainText(
            f"今日反馈\n{result['comment'] or '记录得不错，明天继续。'}"
            f"\n\n建议的明日任务\n{plan or '—'}"
        )
        if result["plan"]:
            self.advisor_draft.setPlainText("\n".join(result["plan"]))
        self.review_status.setText("总结与反思已保存，分析完成。")
        self.review_button.setEnabled(True)
        self.refresh_accountability()
        self.refresh_history()
        self._evaluate_supervision()

    def _review_failed(self, message):
        self.review_status.setText("记录已保存，但 AI 反馈暂时不可用。")
        self.review_button.setEnabled(True)
        QMessageBox.warning(
            self, "AI 暂不可用", f"总结与反思已经安全保存。\n\n{message}"
        )
        self.refresh_history()

    def generate_advisor_plan(self):
        if not self.cfg.ai_enabled:
            self.advisor_analysis.setText(
                "AI 已关闭。任务顾问不会读取或发送你的任务与复盘记录。"
            )
            return
        self.advisor_button.setEnabled(False)
        self.advisor_analysis.setText("正在检查未完成任务和近期记录……")
        db_path = self.db.db_path
        config_path = self.cfg.path

        def work():
            worker_db = DB(db_path)
            try:
                return agent.generate_task_advisor_plan(
                    worker_db, Config(config_path)
                )
            finally:
                worker_db.close()

        self._run_background(work, self._show_advisor_plan, self._advisor_failed)

    def _show_advisor_plan(self, result):
        self.advisor_button.setEnabled(True)
        self.advisor_analysis.setText(result["analysis"] or "已完成任务分析。")
        self.advisor_draft.setPlainText("\n".join(result["tasks"]))

    def _advisor_failed(self, message):
        self.advisor_button.setEnabled(True)
        self.advisor_analysis.setText(f"任务分析暂时失败：{message}")

    def import_advisor_tasks(self):
        titles = [
            line.strip().lstrip("□☐-•·0123456789.、 ")
            for line in self.advisor_draft.toPlainText().splitlines()
            if line.strip()
        ]
        if not titles:
            QMessageBox.warning(self, "没有任务", "请先生成或填写明日任务。")
            return
        tomorrow = (
            get_business_date(self._now_provider()) + timedelta(days=1)
        ).isoformat()
        existing = {
            task["title"].strip()
            for task in agent.prepare_evening_review(self.db, tomorrow)
        }
        added = 0
        for title in titles:
            if title not in existing:
                self.db.add_task(
                    title,
                    source="任务顾问",
                    scheduled_date=tomorrow,
                )
                existing.add(title)
                added += 1
        self.refresh_tasks()
        self.refresh_review()
        self.statusBar().showMessage(
            f"已安排 {added} 项任务到明日（{tomorrow}）", 4000
        )

    def refresh_history(self):
        selected = (
            self.history_dates.currentItem().text()
            if self.history_dates.currentItem()
            else None
        )
        self.history_dates.clear()
        for log in self.db.get_recent_logs(365):
            self.history_dates.addItem(log["log_date"])
        matches = self.history_dates.findItems(
            selected or "", Qt.MatchFlag.MatchExactly
        )
        if matches:
            self.history_dates.setCurrentItem(matches[0])
        elif self.history_dates.count():
            self.history_dates.setCurrentRow(0)
        else:
            self.history_detail.setPlainText("还没有总结与反思记录。")

    def show_history_date(self, log_date):
        if not log_date:
            return
        log = self.db.get_daily_log(log_date)
        reviews = self.db.get_task_reviews(log_date)
        task_lines = [
            f"- [{STATUS_TEXT[review['status']]}] {review['title']}"
            for review in reviews
        ]
        self.history_detail.setPlainText(
            f"{log_date}\n\n"
            f"任务完成情况\n{chr(10).join(task_lines) or '—'}\n\n"
            f"总结与反思\n{(log['summary'] if log else None) or '—'}\n\n"
            f"明日规划\n{(log['plan_next'] if log else None) or '—'}"
        )

    def _scheduled_greeting(self, _slot):
        self.load_greeting()

    def _scheduled_summary(self):
        self._evaluate_supervision(force_review=True)

    def _review_is_due(self):
        summary_time = QTime.fromString(self.cfg.schedule["summary"], "HH:mm")
        return QTime.currentTime() >= summary_time

    def _check_missing_review(self, force=False):
        self._evaluate_supervision(force_review=force)

    def _evaluate_supervision(self, *, now=None, force_review=False):
        if self._closing:
            return None
        now = now or self._now_provider()
        context = get_time_context(now)
        business_date = get_business_date(now).isoformat()
        review_due = force_review or context.slot == "late_night"
        if not review_due:
            summary_time = QTime.fromString(
                self.cfg.schedule["summary"], "HH:mm"
            )
            review_due = QTime(now.hour, now.minute) >= summary_time

        if review_due:
            log = self.db.get_daily_log(business_date)
            if not log or not (log["summary"] or "").strip():
                self.review_status.setText(
                    "已到总结时间，今天还没有填写总结与反思。"
                )
                self.character_window.ask_for_review(REVIEW_REMINDER)
                self.character_window.set_emotion("angry")
                self._notify(
                    f"{self.cfg.persona_name}催你复盘", REVIEW_REMINDER
                )
                return "review"

        if context.slot == "late_night":
            tasks = agent.prepare_evening_review(self.db, business_date)
            pending = [task for task in tasks if task["status"] == "pending"]
            task_text = (
                agent.build_pending_task_reminder(
                    pending, self.cfg, context_label="今天"
                )
                + "但现在继续熬只会透支明天。"
                if pending
                else "今天该做的检查已经结束。"
            )
            self.character_window.urge_sleep(
                task_text
                + "立刻去睡觉。黑眼圈、皮肤状态和明天的专注力都在被熬夜消耗，"
                "别让无效硬撑拖累你成为更好的自己。",
                "angry",
            )
            return "sleep"

        tasks = self.db.get_today_tasks()
        if tasks:
            self.character_window.urge_study(
                agent.build_pending_task_reminder(tasks, self.cfg),
                "angry" if len(tasks) >= 2 else "serious",
            )
            return "study"

        reviewed = agent.prepare_evening_review(self.db)
        if not reviewed:
            self.character_window.ask_for_tasks(
                "你今天还没有写任务呢？没有规划的一天最容易悄悄被浪费。"
                "现在写下要做什么，我来监督你吧。"
            )
            return "plan"
        return None

    def _scheduled_task_reminder(self):
        self._evaluate_supervision()

    def load_greeting(self, slot=None, *, now=None, force=False):
        now = now or self._now_provider()
        context = get_time_context(now)
        business_date = get_business_date(now).isoformat()
        event = f"greeting_{slot or context.slot}"
        if not force and self._event_already_shown(event, business_date):
            return
        self._mark_event_shown(event, business_date)

        if context.slot == "late_night":
            self._evaluate_supervision(now=now)
            return

        tasks = self.db.get_today_tasks()
        if tasks:
            self.character_window.urge_study(
                f"{context.label}，"
                + agent.build_pending_task_reminder(tasks, self.cfg),
            )
        else:
            reviewed = agent.prepare_evening_review(self.db)
            if reviewed:
                self.character_window.set_emotion(
                    "smile", f"{context.label}，今日任务都完成了，继续保持呀。"
                )
            else:
                self.character_window.ask_for_tasks(
                    "你今天还没有写任务呢？时间真的不多了，没有规划的一天很容易被浪费。"
                    "写一下你今天要做什么，我来监督你吧。"
                    "为了变得更好、追上喜欢的人，今天不能再空着过去。"
                )

    def _show_greeting(self, text):
        if self.db.get_today_tasks():
            self.character_window.set_emotion("smile", str(text).strip())
        else:
            self.character_window.ask_for_tasks(str(text).strip())

    def _greeting_failed(self, _message):
        self.character_window.set_emotion(
            "serious", "网络暂时不配合。先把眼前最重要的事做起来。"
        )

    def load_settings(self):
        self.persona_choice.setCurrentText(self.cfg.persona_choice)
        self.persona_name.setText(self.cfg.persona_name)
        self.persona_address.setText(self.cfg.address)
        self.summary_time.setTime(
            QTime.fromString(self.cfg.schedule["summary"], "HH:mm")
        )
        self.quote_interval.setValue(
            int(self.cfg.schedule.get("quote_interval_minutes", 90))
        )
        self.ai_enabled.setChecked(self.cfg.ai_enabled)
        self.startup_enabled.setChecked(
            is_startup_enabled(self._startup_dir)
        )
        self._apply_ai_state()

    def save_settings(self):
        schedule = dict(self.cfg.schedule)
        schedule["summary"] = self.summary_time.time().toString("HH:mm")
        schedule["quote_interval_minutes"] = self.quote_interval.value()
        try:
            self.cfg.save_user_settings(
                persona_choice=self.persona_choice.currentText(),
                persona_name=self.persona_name.text(),
                address=self.persona_address.text(),
                schedule=schedule,
                ai_enabled=self.ai_enabled.isChecked(),
            )
            set_startup_enabled(
                self.startup_enabled.isChecked(),
                startup_dir=self._startup_dir,
            )
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            return
        self.scheduler.reload(self.cfg.schedule)
        self._apply_character_identity()
        self._apply_ai_state()
        self.statusBar().showMessage("设置已保存", 3000)

    def _apply_ai_state(self):
        enabled = self.cfg.ai_enabled
        self.advisor_button.setEnabled(enabled)
        self.review_button.setText(
            "保存并获取反馈" if enabled else "保存到本地"
        )
        if not enabled:
            self.advisor_analysis.setText("AI 已关闭，仅使用本地提醒。")

    def backup_database(self):
        default_name = f"gnomon-backup-{datetime.now():%Y%m%d-%H%M%S}.db"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "备份数据库",
            default_name,
            "SQLite 数据库 (*.db)",
        )
        if not path:
            return
        try:
            self.db.backup_to(path)
        except Exception as exc:
            QMessageBox.critical(self, "备份失败", str(exc))
            return
        self.statusBar().showMessage(f"数据库已备份到 {path}", 5000)

    def export_reviews(self):
        default_name = f"gnomon-reviews-{date.today():%Y%m%d}.md"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出复盘",
            default_name,
            "Markdown 文件 (*.md)",
        )
        if not path:
            return
        try:
            export_reviews_markdown(self.db, path)
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"复盘已导出到 {path}", 5000)

    def _notify(self, title, message):
        if self.tray_icon.isVisible():
            self.tray_icon.showMessage(
                title, message, QSystemTrayIcon.MessageIcon.Information, 8000
            )

    def _tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_main_window()

    def _show_main_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _toggle_character(self):
        if self.character_window.is_collapsed:
            self.character_window.expand()
        elif self.character_window.isVisible():
            self.character_window.collapse()
        else:
            self.character_window.show_near_bottom_right()

    def _quit_application(self):
        self._quit_requested = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _event_key(self, event, event_date=None):
        event_date = event_date or get_business_date().isoformat()
        return f"shown/{self._profile_id}/{event_date}/{event}"

    def _event_already_shown(self, event, event_date=None):
        return self._app_settings.value(
            self._event_key(event, event_date), False, type=bool
        )

    def _mark_event_shown(self, event, event_date=None):
        self._app_settings.setValue(self._event_key(event, event_date), True)

    def _run_background(self, fn, on_success, on_error):
        worker = FunctionWorker(fn)
        worker.succeeded.connect(on_success)
        worker.failed.connect(on_error)
        worker.finished.connect(lambda: self._workers.discard(worker))
        self._workers.add(worker)
        worker.start()

    def closeEvent(self, event):
        if not self._quit_requested:
            self.hide()
            event.ignore()
            return
        if self._closing:
            event.accept()
            return
        self._closing = True
        self._supervision_retry_timer.stop()
        self.review_watch_timer.stop()
        self.scheduler.shutdown()
        self.tray_icon.hide()
        self.task_note.hide()
        self.character_window.close()
        self.db.close()
        event.accept()
