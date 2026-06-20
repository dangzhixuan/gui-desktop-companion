from threading import Thread

from PySide6.QtCore import QObject, Signal


class FunctionWorker(QObject):
    """在线程中执行耗时函数，把结果或异常送回 UI 线程。"""

    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self._thread = None

    def start(self):
        # 网络请求使用守护线程：即使远端服务失去响应，用户也始终可以退出程序。
        self._thread = Thread(target=self.run, daemon=True)
        self._thread.start()

    def run(self):
        try:
            self.succeeded.emit(self.fn())
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()
