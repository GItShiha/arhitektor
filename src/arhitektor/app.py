import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from arhitektor.infrastructure.database import data_directory, open_database
from arhitektor.services import Library
from arhitektor.ui.jobs import Jobs
from arhitektor.ui.theme import STYLE
from arhitektor.ui.window import MainWindow


def main() -> int:
    from arhitektor.update_bootstrap import atomic, route

    try:
        route()
    except (OSError, RuntimeError, ValueError):
        return 1
    app = QApplication(sys.argv)
    app.setApplicationName("Архитектор")
    app.setOrganizationName("Arhitektor")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    directory = data_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            directory / "arhitektor.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        logging.basicConfig(
            level=logging.INFO,
            handlers=[handler],
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    except OSError as error:
        QMessageBox.critical(None, "Каталог данных недоступен", str(error))
        return 1
    lock = QLockFile(str(directory / "application.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        QMessageBox.warning(
            None, "Библиотека уже открыта", "Закройте другой экземпляр Архитектора перед запуском."
        )
        return 1
    splash = QLabel("Архитектор\nОткрытие библиотеки…")
    splash.setMargin(32)
    splash.show()
    startup = Jobs(app)
    windows = []

    def ready(engine):
        window = MainWindow(Library(engine))
        windows.append(window)
        window.show()
        splash.close()

        def healthy():
            import os

            if window.catalog and window.isEnabled():
                if os.environ.get("ARHITEKTOR_READY"):
                    atomic(
                        Path(os.environ["ARHITEKTOR_READY"]),
                        {"token": os.environ.get("ARHITEKTOR_TRIAL")},
                    )
            else:
                QTimer.singleShot(50, healthy)

        QTimer.singleShot(100, healthy)

    def failed(message):
        QMessageBox.critical(splash, "Не удалось открыть библиотеку", message)
        app.exit(1)

    startup.submit(lambda: open_database(directory / "library.sqlite3"), ready, failed)
    result = app.exec()
    startup.shutdown()
    for window in windows:
        window.jobs.shutdown()
        window.library.engine.dispose()
    lock.unlock()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
