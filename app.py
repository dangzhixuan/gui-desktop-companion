import sys

from PySide6.QtCore import QLockFile, QStandardPaths
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("晷")
    app.setQuitOnLastWindowClosed(False)
    lock_path = (
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
        + "/gnomon_desktop_companion.lock"
    )
    instance_lock = QLockFile(lock_path)
    if not instance_lock.tryLock(100):
        return 0
    window = MainWindow()
    window.hide()
    try:
        return app.exec()
    finally:
        instance_lock.unlock()


if __name__ == "__main__":
    raise SystemExit(main())
