from PySide6.QtCore import QObject, Signal


class ReminderBridge(QObject):
    """把 APScheduler 后台线程的事件安全地送回 Qt 主线程。"""

    greeting_due = Signal(str)
    summary_due = Signal()
    task_reminder_due = Signal()

    def emit_greeting(self, slot: str) -> None:
        self.greeting_due.emit(slot)

    def emit_summary(self) -> None:
        self.summary_due.emit()

    def emit_task_reminder(self) -> None:
        self.task_reminder_due.emit()
