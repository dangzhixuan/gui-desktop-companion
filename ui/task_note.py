from datetime import date

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class TaskNoteWindow(QWidget):
    """桌面便签：数据库任务用复选框表示，文本框只用于新增任务。"""

    tasks_saved = Signal(list)
    task_toggled = Signal(int, bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("今日任务便签")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(330, 245)
        self._dragging = False
        self._drag_offset = QPoint()
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(
            """
            QWidget { background: #dfe9df; color: #183c2a; }
            QLabel#noteTitle {
                color: #173d2a; background: transparent;
                font: 700 16px "Microsoft YaHei UI";
            }
            QCheckBox {
                background: transparent; padding: 5px 3px;
                font: 14px "Microsoft YaHei UI";
            }
            QCheckBox:checked { color: #75877a; text-decoration: line-through; }
            QTextEdit {
                color: #213b2d; background: rgba(250,252,249,205);
                border: 1px solid #bdcdbf; border-radius: 6px;
                padding: 8px; font: 14px "Microsoft YaHei UI";
                selection-background-color: #527b63;
            }
            QPushButton {
                color: #294b37; background: transparent; border: 0;
                padding: 7px 12px; font: 14px "Microsoft YaHei UI";
            }
            QPushButton:hover { background: rgba(43, 83, 59, 22); }
            QPushButton#saveNote {
                color: white; background: #24513b;
                border: 1px solid #24513b;
                border-radius: 7px; font-weight: 600;
            }
            QPushButton#saveNote:hover { background: #183d2b; }
            QScrollArea { background: transparent; border: 0; }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("今日任务")
        title.setObjectName("noteTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self.date_label = QLabel()
        self.date_label.setStyleSheet(
            "color: #607567; font-size: 12px; background: transparent;"
        )
        title_row.addWidget(self.date_label)
        close_button = QPushButton("×")
        close_button.setToolTip("关闭便签")
        close_button.clicked.connect(self.hide)
        title_row.addWidget(close_button)
        layout.addLayout(title_row)
        self.refresh_date()

        hint = QLabel("勾选后才算完成")
        hint.setStyleSheet("color: #607567; font-size: 12px;")
        layout.addWidget(hint)

        self.task_container = QWidget()
        self.task_layout = QVBoxLayout(self.task_container)
        self.task_layout.setContentsMargins(2, 2, 2, 2)
        self.task_layout.setSpacing(2)
        self.task_layout.addStretch()
        task_scroll = QScrollArea()
        task_scroll.setWidgetResizable(True)
        task_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        task_scroll.setWidget(self.task_container)
        layout.addWidget(task_scroll, 1)

        add_hint = QLabel("新增任务（一行一项）")
        add_hint.setStyleSheet("color: #607567; font-size: 12px;")
        layout.addWidget(add_hint)
        self.editor = QTextEdit()
        self.editor.setFixedHeight(48)
        self.editor.setPlaceholderText("完成阅读论文一篇")
        layout.addWidget(self.editor)

        save = QPushButton("保存")
        save.setObjectName("saveNote")
        save.clicked.connect(self._save)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)

    def set_tasks(self, tasks):
        self.refresh_date()
        while self.task_layout.count() > 1:
            item = self.task_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for task in tasks:
            checkbox = QCheckBox(task["title"])
            is_done = task["status"] == "done"
            checkbox.setChecked(is_done)
            checkbox.stateChanged.connect(
                lambda state, task_id=task["id"]: self._toggle_task(
                    task_id, state
                )
            )
            self.task_layout.insertWidget(self.task_layout.count() - 1, checkbox)

        if not tasks:
            empty = QLabel("还没有任务")
            empty.setStyleSheet("color: #718276; padding: 8px;")
            self.task_layout.insertWidget(0, empty)
        self.editor.clear()

    def refresh_date(self):
        today = date.today()
        weekdays = "一二三四五六日"
        self.date_label.setText(
            f"{today:%Y.%m.%d}  周{weekdays[today.weekday()]}"
        )

    def _toggle_task(self, task_id, state):
        is_done = state == Qt.CheckState.Checked.value
        self.task_toggled.emit(int(task_id), is_done)

    def _save(self):
        tasks = [
            line.strip().lstrip("□☐-•·0123456789.、 ")
            for line in self.editor.toPlainText().splitlines()
            if line.strip()
        ]
        if tasks:
            self.tasks_saved.emit(tasks)

    def closeEvent(self, event: QCloseEvent):
        event.ignore()
        self.hide()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 52:
            self._dragging = True
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)
