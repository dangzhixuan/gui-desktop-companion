from pathlib import Path
import re
import sys

from PySide6.QtCore import QEvent, QPoint, QSettings, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


APP_DIR = (
    Path(sys._MEIPASS)
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
ASSET_DIR = APP_DIR / "assets" / "character"
EMOTION_ASSETS = {
    "smile": ASSET_DIR / "luwenxi_smile.png",
    "serious": ASSET_DIR / "luwenxi_serious.png",
    "angry": ASSET_DIR / "luwenxi_angry.png",
}


class BubbleTail(QWidget):
    """绘制向下的气泡尖角，避免依赖字体中的三角形字符。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(24, 14)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        points = QPolygon(
            [
                QPoint(1, 0),
                QPoint(self.width() - 2, 0),
                QPoint(self.width() // 2, self.height() - 1),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(247, 250, 246, 242))
        painter.drawPolygon(points)
        painter.setPen(QPen(QColor(151, 170, 153, 245), 1))
        painter.drawLine(points[0], points[2])
        painter.drawLine(points[2], points[1])


class CharacterWindow(QWidget):
    """透明置顶的静态角色小窗，后续可在此处替换为 Live2D 渲染。"""

    activated = Signal()
    character_clicked = Signal()
    action_requested = Signal(str)
    action_finished = Signal(str)
    note_requested = Signal()
    RESPONSE_TIMEOUT_MS = 5 * 60 * 1000
    EXPANDED_SIZE = QSize(285, 430)
    MIN_EXPANDED_SIZE = QSize(220, 330)
    MAX_EXPANDED_SIZE = QSize(520, 780)
    COLLAPSED_SIZE = QSize(62, 62)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("陆文昔")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(self.EXPANDED_SIZE)

        self._pixmaps = {}
        self._emotion = "smile"
        self._drag_offset = QPoint()
        self._press_position = QPoint()
        self._moved_during_press = False
        self._dragging = False
        self._awaiting_response = False
        self._message_pages = []
        self._page_index = 0
        self._pending_action = (None, None)
        self._full_message_mode = False
        self._collapsed = False
        self._expanded_position = QPoint()
        self._settings = QSettings("Gnomon", "DesktopCompanion")
        self._size_save_timer = QTimer(self)
        self._size_save_timer.setSingleShot(True)
        self._size_save_timer.timeout.connect(self._save_expanded_size)

        self._response_timer = QTimer(self)
        self._response_timer.setSingleShot(True)
        self._response_timer.timeout.connect(self._become_angry_if_waiting)

        self._build_ui()
        self._load_assets()
        self.set_emotion("smile")
        self.bubble_card.hide()

    @property
    def emotion(self):
        return self._emotion

    @property
    def is_collapsed(self):
        return self._collapsed

    def _build_ui(self):
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(6, 6, 6, 6)
        self.root_layout.setSpacing(3)

        self.bubble_row = QHBoxLayout()
        self.bubble_row.addStretch()
        self.bubble_card = QWidget()
        self.bubble_card.setObjectName("bubbleCard")
        bubble_layout = QVBoxLayout(self.bubble_card)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(0)

        self.bubble_panel = QWidget()
        self.bubble_panel.setObjectName("bubblePanel")
        panel_layout = QVBoxLayout(self.bubble_panel)
        panel_layout.setContentsMargins(14, 12, 14, 10)
        panel_layout.setSpacing(8)

        self.bubble = QLabel()
        self.bubble.setObjectName("speechBubble")
        self.bubble.setWordWrap(True)
        self.bubble.setMaximumWidth(220)
        self.bubble.setMinimumWidth(155)
        self.bubble.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        panel_layout.addWidget(self.bubble)

        self.action_button = QPushButton()
        self.action_button.setObjectName("bubbleAction")
        self.action_button.hide()
        self.action_button.clicked.connect(self._emit_action)
        panel_layout.addWidget(
            self.action_button, alignment=Qt.AlignmentFlag.AlignRight
        )

        self.continue_button = QPushButton("继续点击 ›")
        self.continue_button.setObjectName("continueHint")
        self.continue_button.hide()
        self.continue_button.clicked.connect(self.show_next_message)
        panel_layout.addWidget(
            self.continue_button, alignment=Qt.AlignmentFlag.AlignRight
        )
        bubble_layout.addWidget(self.bubble_panel)

        tail_row = QHBoxLayout()
        tail_row.setContentsMargins(0, 0, 24, 0)
        tail_row.addStretch()
        self.bubble_tail = BubbleTail()
        self.bubble_tail.setObjectName("bubbleTail")
        tail_row.addWidget(self.bubble_tail)
        bubble_layout.addLayout(tail_row)
        self.bubble_row.addWidget(self.bubble_card)
        self.root_layout.addLayout(self.bubble_row)

        self.character_stage = QWidget()
        self.character_stage.setObjectName("characterStage")
        stage_layout = QGridLayout(self.character_stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)

        self.character = QLabel()
        self.character.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom
        )
        self.character.setMinimumSize(QSize(235, 285))
        stage_layout.addWidget(self.character, 0, 0)

        self.controls = QWidget()
        self.controls.setObjectName("characterControls")
        note_row = QHBoxLayout(self.controls)
        note_row.setContentsMargins(8, 0, 6, 7)
        self.collapse_button = QPushButton("收起")
        self.collapse_button.setObjectName("collapseButton")
        self.collapse_button.setToolTip("收起为桌面边缘小挂件")
        self.collapse_button.clicked.connect(self.collapse)
        note_row.addWidget(self.collapse_button)
        note_row.addStretch()
        self.note_button = QPushButton("📝 今日便签")
        self.note_button.setObjectName("noteButton")
        self.note_button.clicked.connect(self.note_requested)
        note_row.addWidget(self.note_button)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setToolTip("拖动调节角色大小")
        self.size_grip.setFixedSize(18, 18)
        note_row.addWidget(self.size_grip)
        stage_layout.addWidget(
            self.controls,
            0,
            0,
            alignment=Qt.AlignmentFlag.AlignBottom,
        )
        self.root_layout.addWidget(self.character_stage, 1)

        self.launcher_button = QPushButton("晷")
        self.launcher_button.setObjectName("launcherButton")
        self.launcher_button.setToolTip("点击展开晷")
        self.launcher_button.installEventFilter(self)
        self.launcher_button.hide()
        self.root_layout.addWidget(self.launcher_button)

        self.setStyleSheet(
            """
            QWidget#bubbleCard { background: transparent; }
            QWidget#bubblePanel {
                background: rgba(247, 250, 246, 242);
                border: 1px solid rgba(151, 170, 153, 245);
                border-radius: 14px;
            }
            QWidget#characterStage, QWidget#characterControls {
                background: transparent;
            }
            QLabel#speechBubble {
                color: #21372c;
                background: transparent;
                border: 0;
                padding: 0;
                font: 13px "Microsoft YaHei UI";
            }
            QPushButton#bubbleAction {
                color: white;
                background: #24513b;
                border: 0;
                border-radius: 7px;
                padding: 6px 12px;
                font: 13px "Microsoft YaHei UI";
            }
            QPushButton#bubbleAction:hover { background: #183d2b; }
            QPushButton#continueHint {
                color: #7a8d80;
                background: transparent;
                border: 0;
                padding: 0;
                font: 11px "Microsoft YaHei UI";
            }
            QPushButton#continueHint:hover { color: #315d45; }
            QPushButton#noteButton {
                color: #234735; background: rgba(221, 233, 218, 185);
                border: 1px solid rgba(132, 162, 138, 190);
                border-radius: 8px; padding: 5px 9px;
                font: 11px "Microsoft YaHei UI";
            }
            QPushButton#noteButton:hover {
                background: rgba(203, 220, 200, 235);
            }
            QPushButton#collapseButton {
                color: #3f5f4c; background: rgba(242,247,241,165);
                border: 1px solid rgba(150,174,154,185);
                border-radius: 8px; padding: 5px 8px;
                font: 11px "Microsoft YaHei UI";
            }
            QPushButton#collapseButton:hover {
                color: #173d2a; background: rgba(226,235,224,230);
            }
            QPushButton#launcherButton {
                color: #f4f7f2; background: #285943;
                border: 2px solid #dce8dc; border-radius: 23px;
                min-width: 46px; min-height: 46px;
                max-width: 46px; max-height: 46px;
                font: 600 18px "Microsoft YaHei UI";
            }
            QPushButton#launcherButton:hover {
                background: #1c4935;
                border-color: #b8ccb9;
            }
            """
        )

    def _load_assets(self):
        for emotion, path in EMOTION_ASSETS.items():
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self._pixmaps[emotion] = pixmap

    def set_emotion(
        self,
        emotion,
        message=None,
        *,
        action_label=None,
        action_id=None,
    ):
        if emotion not in self._pixmaps:
            emotion = "smile" if "smile" in self._pixmaps else next(
                iter(self._pixmaps), emotion
            )
        self._emotion = emotion
        if message:
            self.set_message(
                message,
                action_label=action_label,
                action_id=action_id,
            )
        self._update_character_pixmap()

    def set_message(self, message, *, action_label=None, action_id=None):
        if not self._collapsed:
            self.bubble_card.show()
        self._full_message_mode = False
        text = str(message).strip()
        self._message_pages = self._split_message(text)
        self._page_index = 0
        self._pending_action = (action_label, action_id)
        self._show_current_page()

    def show_full_message(
        self,
        message,
        *,
        action_label="我知道了",
        action_id="dismiss",
    ):
        if not self._collapsed:
            self.bubble_card.show()
        self._full_message_mode = True
        self._message_pages = [str(message).strip() or "……"]
        self._page_index = 0
        self._pending_action = (action_label, action_id)
        self.bubble.setText(self._message_pages[0])
        self.continue_button.hide()
        self.action_button.setText(action_label)
        self.action_button.setProperty("action_id", action_id)
        self.action_button.show()

    def hide_bubble(self):
        self.bubble_card.hide()

    @staticmethod
    def _split_message(text):
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return ["……"]
        sentences = [
            part.strip()
            for part in re.findall(r"[^。！？!?；;]+[。！？!?；;]?", text)
            if part.strip()
        ]
        pages = []
        for sentence in sentences or [text]:
            while len(sentence) > 42:
                pages.append(sentence[:42].rstrip() + "……")
                sentence = sentence[42:].lstrip()
            if sentence:
                pages.append(sentence)
        return pages or ["……"]

    def _show_current_page(self):
        self.bubble.setText(self._message_pages[self._page_index])
        has_more = self._page_index < len(self._message_pages) - 1
        self.continue_button.setVisible(has_more)
        action_label, action_id = self._pending_action
        if not has_more and action_label and action_id:
            self.action_button.setText(action_label)
            self.action_button.setProperty("action_id", action_id)
            self.action_button.show()
        else:
            self.action_button.setProperty("action_id", "")
            self.action_button.hide()
        self.bubble.adjustSize()

    def show_next_message(self):
        if self._page_index < len(self._message_pages) - 1:
            self._page_index += 1
            self._show_current_page()

    def ask_for_review(self, message):
        self._awaiting_response = True
        self.set_emotion(
            "serious",
            message,
            action_label="我这就写总结",
            action_id="review",
        )
        self._response_timer.start(self.RESPONSE_TIMEOUT_MS)

    def ask_for_tasks(self, message="今天想完成什么？先告诉我吧。"):
        self.set_emotion("smile")
        self.show_full_message(
            message,
            action_label="我这就写规划",
            action_id="plan",
        )

    def urge_study(self, message, emotion="serious"):
        self.set_emotion(
            emotion,
            message,
            action_label="我这就滚去学习",
            action_id="study",
        )

    def urge_sleep(self, message, emotion="serious"):
        self.set_emotion(
            emotion,
            message,
            action_label="我这就滚去睡觉",
            action_id="sleep",
        )

    def mark_engaged(self, message="我在这里等你写完。"):
        self._awaiting_response = False
        self._response_timer.stop()
        self.set_emotion("serious", message)

    def acknowledge_response(self, message="好，我看见你开始行动了。"):
        self._awaiting_response = False
        self._response_timer.stop()
        self.set_emotion("smile", message)

    def _become_angry_if_waiting(self):
        if self._awaiting_response:
            self.set_emotion(
                "angry",
                "我还在等你写总结。时间不多了，再逃避只会让今天的教训白白流走。",
                action_label="我这就写总结",
                action_id="review",
            )

    def _emit_action(self):
        action_id = self.action_button.property("action_id")
        if action_id in {"dismiss", "quote_dismiss", "sleep", "study"}:
            if action_id == "study":
                self._awaiting_response = False
                self._response_timer.stop()
            self.hide_bubble()
            if action_id != "dismiss":
                self.action_finished.emit(str(action_id))
            return
        if action_id == "plan":
            self.action_requested.emit("tasks")
            return
        if action_id:
            self.action_requested.emit(str(action_id))

    def _update_character_pixmap(self):
        pixmap = self._pixmaps.get(self._emotion)
        if pixmap is None:
            self.character.clear()
            return
        target = self.character.size()
        self.character.setPixmap(
            pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_character_pixmap()
        if not self._collapsed and self.isVisible():
            self._size_save_timer.start(250)

    def _save_expanded_size(self):
        if not self._collapsed:
            self._settings.setValue("character_size", self.size())

    def collapse(self):
        if self._collapsed:
            return
        self._expanded_position = self.pos()
        self._settings.setValue("character_position", self._expanded_position)
        self._settings.setValue("character_size", self.size())
        self._collapsed = True
        self._settings.setValue("character_collapsed", True)
        self.bubble_card.hide()
        self.character.hide()
        self.controls.hide()
        self.character_stage.hide()
        self.size_grip.hide()
        self.launcher_button.show()
        self.root_layout.setContentsMargins(6, 6, 6, 6)
        self.setMinimumSize(self.COLLAPSED_SIZE)
        self.setMaximumSize(self.COLLAPSED_SIZE)
        self.resize(self.COLLAPSED_SIZE)
        screen = self.screen() or QApplication.primaryScreen()
        saved_collapsed = self._settings.value("character_collapsed_position")
        if isinstance(saved_collapsed, QPoint):
            self.move(saved_collapsed)
        elif screen:
            area = screen.availableGeometry()
            self.move(
                area.right() - self.width() - 8,
                min(max(self.y(), area.top() + 8), area.bottom() - self.height() - 8),
            )
        self.raise_()

    def expand(self):
        if not self._collapsed:
            self.show()
            self.raise_()
            return
        self._collapsed = False
        self._settings.setValue("character_collapsed", False)
        self.launcher_button.hide()
        self.character_stage.show()
        self.character.show()
        self.controls.show()
        self.size_grip.show()
        self.setMinimumSize(self.MIN_EXPANDED_SIZE)
        self.setMaximumSize(self.MAX_EXPANDED_SIZE)
        if self._message_pages:
            self.bubble_card.show()
        saved_size = self._settings.value("character_size")
        if isinstance(saved_size, QSize):
            width = min(
                max(saved_size.width(), self.MIN_EXPANDED_SIZE.width()),
                self.MAX_EXPANDED_SIZE.width(),
            )
            height = min(
                max(saved_size.height(), self.MIN_EXPANDED_SIZE.height()),
                self.MAX_EXPANDED_SIZE.height(),
            )
            self.resize(width, height)
        else:
            self.resize(self.EXPANDED_SIZE)
        saved = self._expanded_position or self._settings.value("character_position")
        if isinstance(saved, QPoint):
            self.move(saved)
        self._update_character_pixmap()
        self.show()
        self.raise_()

    def show_near_bottom_right(self):
        self.setMinimumSize(self.MIN_EXPANDED_SIZE)
        self.setMaximumSize(self.MAX_EXPANDED_SIZE)
        saved_size = self._settings.value("character_size")
        if isinstance(saved_size, QSize):
            width = min(
                max(saved_size.width(), self.MIN_EXPANDED_SIZE.width()),
                self.MAX_EXPANDED_SIZE.width(),
            )
            height = min(
                max(saved_size.height(), self.MIN_EXPANDED_SIZE.height()),
                self.MAX_EXPANDED_SIZE.height(),
            )
            self.resize(width, height)
        saved = self._settings.value("character_position")
        if isinstance(saved, QPoint):
            self.move(saved)
        else:
            screen = QApplication.primaryScreen()
            if screen:
                area = screen.availableGeometry()
                self.move(
                    area.right() - self.width() - 18,
                    area.bottom() - self.height() - 18,
                )
        self.show()
        if self._settings.value("character_collapsed", False, type=bool):
            # 先以展开位置初始化，再收起到屏幕边缘。
            self._collapsed = False
            self.collapse()
        self.raise_()

    def _begin_drag(self, global_position):
        self._press_position = global_position
        self._moved_during_press = False
        self._drag_offset = global_position - self.frameGeometry().topLeft()
        self._dragging = True

    def _continue_drag(self, global_position):
        if not self._dragging:
            return
        if (
            global_position - self._press_position
        ).manhattanLength() > QApplication.startDragDistance():
            self._moved_during_press = True
        self.move(global_position - self._drag_offset)

    def _finish_drag(self):
        was_dragging = self._dragging
        self._dragging = False
        if not was_dragging:
            return
        if self._collapsed:
            self._settings.setValue("character_collapsed_position", self.pos())
            if not self._moved_during_press:
                self.expand()
        else:
            self._settings.setValue("character_position", self.pos())
            if not self._moved_during_press:
                self.character_clicked.emit()

    def eventFilter(self, watched, event):
        if watched is self.launcher_button:
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._begin_drag(event.globalPosition().toPoint())
                return True
            if (
                event.type() == QEvent.Type.MouseMove
                and event.buttons() & Qt.MouseButton.LeftButton
            ):
                self._continue_drag(event.globalPosition().toPoint())
                return True
            if (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._finish_drag()
                return True
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._dragging and event.buttons() & Qt.MouseButton.LeftButton:
            self._continue_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._finish_drag()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
