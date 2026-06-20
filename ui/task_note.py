from datetime import date

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QCloseEvent, QMouseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
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
        self.setMinimumSize(280, 220)
        self._dragging = False
        self._drag_offset = QPoint()
        self._tasks = []
        self._draft_titles = []
        self._resize_margin = 7
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
            QLineEdit {
                color: #213b2d; background: rgba(250,252,249,205);
                border: 1px solid #bdcdbf; border-radius: 6px;
                padding: 8px; font: 14px "Microsoft YaHei UI";
                selection-background-color: #527b63;
            }
            QCheckBox[draft="true"] {
                color: #456653; font-style: italic;
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

        add_hint = QLabel("新增任务（输入后按回车加入上方）")
        add_hint.setStyleSheet("color: #607567; font-size: 12px;")
        layout.addWidget(add_hint)
        self.editor = QLineEdit()
        self.editor.setFixedHeight(42)
        self.editor.setPlaceholderText("完成阅读论文一篇")
        self.editor.returnPressed.connect(self._stage_editor_task)
        layout.addWidget(self.editor)

        save = QPushButton("保存")
        save.setObjectName("saveNote")
        save.clicked.connect(self._save)
        layout.addWidget(save, alignment=Qt.AlignmentFlag.AlignRight)

    def set_tasks(self, tasks):
        self.refresh_date()
        self._tasks = list(tasks)
        self._draft_titles.clear()
        self.editor.clear()
        self._render_tasks()

    def _render_tasks(self):
        while self.task_layout.count() > 1:
            item = self.task_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for task in self._tasks:
            checkbox = QCheckBox(task["title"])
            is_done = task["status"] == "done"
            checkbox.setChecked(is_done)
            checkbox.stateChanged.connect(
                lambda state, task_id=task["id"]: self._toggle_task(
                    task_id, state
                )
            )
            self.task_layout.insertWidget(self.task_layout.count() - 1, checkbox)

        for title in self._draft_titles:
            checkbox = QCheckBox(f"{title}  （待保存）")
            checkbox.setProperty("draft", True)
            checkbox.setEnabled(False)
            self.task_layout.insertWidget(self.task_layout.count() - 1, checkbox)

        if not self._tasks and not self._draft_titles:
            empty = QLabel("还没有任务")
            empty.setStyleSheet("color: #718276; padding: 8px;")
            self.task_layout.insertWidget(0, empty)

    @staticmethod
    def _clean_title(text):
        return str(text).strip().lstrip("□☐-•·0123456789.、 ")

    def _stage_editor_task(self):
        title = self._clean_title(self.editor.text())
        if not title:
            return
        existing = {
            task["title"].strip()
            for task in self._tasks
        } | set(self._draft_titles)
        self.editor.clear()
        if title in existing:
            return
        self._draft_titles.append(title)
        self._render_tasks()
        self.editor.setFocus()

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
        self._stage_editor_task()
        tasks = list(self._draft_titles)
        if tasks:
            self._draft_titles.clear()
            self.tasks_saved.emit(tasks)

    def closeEvent(self, event: QCloseEvent):
        event.ignore()
        self.hide()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._resize_edges_at(event.position().toPoint())
            if edges and self.windowHandle():
                self.windowHandle().startSystemResize(edges)
                event.accept()
                return
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
        self._update_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if not self._dragging:
            self.unsetCursor()
        super().leaveEvent(event)

    def _resize_edges_at(self, position):
        edges = Qt.Edges()
        if position.x() <= self._resize_margin:
            edges |= Qt.Edge.LeftEdge
        elif position.x() >= self.width() - self._resize_margin:
            edges |= Qt.Edge.RightEdge
        if position.y() <= self._resize_margin:
            edges |= Qt.Edge.TopEdge
        elif position.y() >= self.height() - self._resize_margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _update_resize_cursor(self, position):
        edges = self._resize_edges_at(position)
        if edges in (
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge,
        ):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges in (
            Qt.Edge.RightEdge | Qt.Edge.TopEdge,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge,
        ):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()
