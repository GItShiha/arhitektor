"""Asynchronous update checks, persistent preferences, explicit installation consent."""

import json
import os
import subprocess
import sys
import time

from PySide6.QtCore import QProcess, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from arhitektor.update_bootstrap import install_launcher, read_json, state_dir
from arhitektor.updater import ROOT


class Updates(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.settings = window.settings
        self.target = None
        self.current = "не определена"
        self.process = None
        self.gate = None
        self.installer = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Обновления"))
        self.auto = QCheckBox("Проверять обновления автоматически")
        self.auto.setChecked(self.settings.value("updates/auto", True, type=bool))
        self.notify = QCheckBox("Показывать уведомления")
        self.notify.setChecked(self.settings.value("updates/notify", True, type=bool))
        self.interval = QComboBox()
        for hours in (1, 6, 24):
            self.interval.addItem(f"Каждые {hours} ч", hours)
        self.interval.setCurrentIndex(
            max(0, self.interval.findData(self.settings.value("updates/hours", 6, type=int)))
        )
        self.status = QLabel("Проверка ещё не выполнялась")
        self.status.setWordWrap(True)
        self.revision = QLabel()
        self.last = QLabel()
        self.history = QLabel()
        self.history.setWordWrap(True)
        self.check_button = QPushButton("Проверить сейчас")
        self.check_button.clicked.connect(lambda: self.check(True))
        self.install_button = QPushButton("Обновить")
        self.install_button.clicked.connect(self.confirm)
        self.install_button.setEnabled(False)
        self.rollback_button = QPushButton("Вернуться к предыдущей версии")
        self.rollback_button.clicked.connect(lambda: self.confirm(rollback=True))
        setup = QPushButton("Установить постоянный запускатель и ярлык KDE")
        setup.clicked.connect(self.setup)
        journal = QPushButton("Открыть журнал обновлений")
        journal.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(state_dir())))
        )
        for widget in (
            self.auto,
            self.notify,
            self.interval,
            self.revision,
            self.last,
            self.status,
            self.check_button,
            self.install_button,
            self.history,
            self.rollback_button,
            setup,
            journal,
        ):
            layout.addWidget(widget)
        self.notice = QWidget(window.page)
        banner = QVBoxLayout(self.notice)
        banner.addWidget(QLabel("Доступно обновление Архитектора"))
        for label, callback in (
            ("Обновить", self.confirm),
            ("Позже", self.later),
            ("Подробнее", self.details),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            banner.addWidget(button)
        window.page.layout().insertWidget(1, self.notice)
        self.notice.hide()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check)
        self.auto.toggled.connect(self.configure)
        self.notify.toggled.connect(self.configure)
        self.interval.currentIndexChanged.connect(self.configure)
        self.enabled = sys.platform.startswith("linux") and not os.environ.get("ARHITEKTOR_PROBE")
        self.configure()
        self.refresh_labels()
        self.hide()
        if self.enabled:
            QTimer.singleShot(100, self, lambda: self.command("revision", self.got_revision))
            QTimer.singleShot(2500, self, lambda: self.check() if self.auto.isChecked() else None)
        else:
            self.status.setText("Автообновление доступно только в Linux (отключено при проверках).")
            self.check_button.setEnabled(False)
            self.rollback_button.setEnabled(False)
            setup.setEnabled(False)

    def configure(self, *_):
        for key, value in (
            ("auto", self.auto.isChecked()),
            ("notify", self.notify.isChecked()),
            ("hours", self.interval.currentData()),
        ):
            self.settings.setValue("updates/" + key, value)
        self.timer.stop()
        if self.auto.isChecked() and self.enabled:
            self.timer.start(self.interval.currentData() * 3600000)
        if not self.notify.isChecked():
            self.notice.hide()

    def refresh_labels(self):
        self.revision.setText("Установленная ревизия: " + self.current[:12])
        self.last.setText(
            "Последняя успешная проверка: "
            + self.settings.value("updates/last", "ещё не выполнялась")
        )
        journal = read_json(state_dir() / "transaction.json", {})
        self.history.setText(
            "Последняя установка: "
            + journal.get("completed_at", "нет")
            + "\n"
            + journal.get("error", journal.get("phase", ""))
        )
        self.rollback_button.setEnabled(False)
        if self.enabled and journal.get("phase") == "complete" and journal.get("previous"):
            self.command(
                "rollback-check",
                lambda _: self.rollback_button.setEnabled(True),
                ["--database", str(self.window.library.engine.url.database)],
            )

    def open_settings(self):
        dialog = QDialog(self.window)
        dialog.setWindowTitle("Обновления")
        dialog.resize(620, 540)
        layout = QVBoxLayout(dialog)
        layout.addWidget(self)
        self.refresh_labels()
        self.show()
        dialog.exec()
        self.hide()
        self.setParent(self.window)
        dialog.deleteLater()

    def command(self, action, callback, extra=()):
        if not self.enabled or self.process is not None:
            return
        self.process = QProcess(self)
        process = self.process
        process.setProgram(sys.executable)
        process.setArguments(["-m", "arhitektor.updater", action, "--root", str(ROOT), *extra])
        self.check_button.setEnabled(False)

        def done(*_):
            if self.process is not process:
                return
            try:
                result = json.loads(bytes(process.readAllStandardOutput()))
            except (ValueError, UnicodeError):
                result = {"error": "Проверка недоступна. Повторите позже."}
            self.process = None
            process.deleteLater()
            self.check_button.setEnabled(True)
            if "error" in result:
                self.target = None
                self.install_button.setEnabled(False)
                self.notice.hide()
                self.status.setText(result["error"])
            else:
                callback(result)

        process.finished.connect(done)
        process.errorOccurred.connect(
            lambda error: done() if error == QProcess.ProcessError.FailedToStart else None
        )
        process.start()

    def got_revision(self, value):
        self.current = value["revision"]
        self.refresh_labels()

    def check(self, manual=False):
        if self.enabled and self.process is None:
            self.status.setText("Проверка обновлений…")
            self.command("check", lambda result: self.checked(result, manual))

    def checked(self, result, manual=False):
        self.current = result["current"]
        self.target = result["target"] if result["available"] else None
        self.settings.setValue("updates/last", result["checked_at"])
        self.status.setText(
            "Доступно обновление" if self.target else "Установлена последняя версия"
        )
        self.install_button.setEnabled(bool(self.target))
        self.notice.setVisible(
            bool(self.target)
            and (
                manual
                or (
                    self.notify.isChecked()
                    and self.settings.value("updates/dismissed") != self.target
                )
            )
        )
        self.refresh_labels()

    def later(self):
        self.settings.setValue("updates/dismissed", self.target)
        self.notice.hide()

    def details(self):
        QMessageBox.information(
            self.window,
            "Об обновлении",
            "Источник: github.com/GItShiha/arhitektor, main\nТекущая ревизия: "
            + self.current
            + "\nНовая ревизия: "
            + (self.target or "нет")
            + "\nБудут созданы отдельная версия, окружение и проверенная копия SQLite. "
            "Проверки выполняются на копии данных. Изменения схемы блокируются. "
            "Приложение будет перезапущено; при откате актуальные тексты сохраняются.",
        )

    def confirm(self, _checked=False, rollback=False):
        if self.installer or (not self.target and not rollback):
            return
        answer = QMessageBox.question(
            self.window,
            "Вернуться?" if rollback else "Установить обновление?",
            "Работа будет сохранена, приложение закроется и перезапустится. "
            "Установка может занять несколько минут. Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def ready(_):
            self.window.guard(lambda: self.close_for_install(rollback))

        if rollback:
            ready(None)
        else:
            self.command(
                "preflight",
                ready,
                [
                    "--target",
                    self.target,
                    "--database",
                    str(self.window.library.engine.url.database),
                ],
            )

    def close_for_install(self, rollback=False):
        def spawn():
            read_fd, write_fd = os.pipe()
            try:
                self.installer = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "arhitektor.updater",
                        "rollback" if rollback else "install",
                        "--root",
                        str(ROOT),
                        "--target",
                        self.target or "rollback",
                        "--database",
                        str(self.window.library.engine.url.database),
                        "--wait-fd",
                        str(read_fd),
                    ],
                    pass_fds=(read_fd,),
                    start_new_session=True,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                os.close(write_fd)
                raise
            finally:
                os.close(read_fd)
            self.gate = write_fd  # Closed by the OS only after app cleanup and actual process exit.
            try:
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "arhitektor.update_progress",
                        "--since",
                        str(time.time()),
                    ],
                    start_new_session=True,
                )
            except OSError:
                pass  # Installation and its durable journal remain available.

        self.window.close_action = spawn
        # Closing a settings dialog must not quit the event loop before the window drains saves.
        if isinstance(self.parentWidget(), QDialog):
            self.parentWidget().accept()
        self.window.close()

    def setup(self):
        from arhitektor.updater import version

        try:
            path = install_launcher(version())
        except (OSError, RuntimeError) as error:
            QMessageBox.warning(self.window, "Запускатель", str(error))
        else:
            QMessageBox.information(self.window, "Запускатель готов", str(path))

    def shutdown(self):
        self.enabled = False
        self.timer.stop()
        if self.process:
            self.process.kill()
            self.process.waitForFinished(1000)
