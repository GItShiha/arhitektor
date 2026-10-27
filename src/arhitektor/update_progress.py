"""Independent progress window; closing it does not cancel installation."""

import argparse

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel

from arhitektor.ui.theme import STYLE
from arhitektor.update_bootstrap import read_json, state_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", type=float, default=0)
    args = parser.parse_args()
    app = QApplication([])
    app.setStyleSheet(STYLE)
    label = QLabel("Подготовка обновления…\nОжидание закрытия Архитектора")
    label.setWindowTitle("Обновление Архитектора")
    label.setMargin(28)
    label.resize(520, 180)
    label.show()
    names = {
        "preparing": "Подготовка новой версии и зависимостей",
        "backing_up": "Создание резервной копии",
        "testing": "Проверка новой версии на копии библиотеки",
        "launching": "Запуск новой версии",
        "complete": "Обновление завершено",
        "rolled_back": "Возврат завершён",
        "failed": "Не удалось установить обновление",
        "blocked": "Возврат заблокирован",
    }

    def refresh():
        path = state_dir() / "transaction.json"
        if not path.exists() or path.stat().st_mtime < args.since:
            return
        journal = read_json(path, {})
        phase = journal.get("phase")
        label.setText(
            names.get(phase, "Ожидание установщика…")
            + "\n"
            + journal.get("error", "")
            + "\nЖурнал: "
            + str(state_dir())
        )
        if phase in ("complete", "rolled_back"):
            QTimer.singleShot(3000, app.quit)
            timer.stop()

    timer = QTimer()
    timer.timeout.connect(refresh)
    timer.start(500)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
