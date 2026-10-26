import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from arhitektor.services import Library, count_words
from arhitektor.ui.jobs import Jobs

NAMES = {"universe": "Вселенная", "article": "Статья", "work": "Произведение", "scene": "Сцена"}


class MainWindow(QMainWindow):
    def __init__(self, library: Library):
        super().__init__()
        self.library = library
        self.jobs = Jobs(self)
        self.selected: tuple[str, int] | None = None
        self.catalog: dict[str, list[dict[str, Any]]] = {}
        self.fields: dict[str, Any] = {}
        self.revision = 0
        self.dirty = False
        self.loading = False
        self.saving = False
        self.closing = False
        self.setWindowTitle("Архитектор — мастерская писателя")
        self.resize(1180, 780)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.save)
        split = QSplitter()
        self.setCentralWidget(split)
        left = QWidget()
        navigation = QVBoxLayout(left)
        heading = QLabel("Архитектор")
        heading.setObjectName("heading")
        navigation.addWidget(heading)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self.choose)
        navigation.addWidget(self.tree)
        add = QPushButton("＋ Создать")
        add.clicked.connect(self.create_dialog)
        navigation.addWidget(add)
        settings = QPushButton("Настройки и данные")
        settings.clicked.connect(lambda: self.guard(self.show_settings))
        navigation.addWidget(settings)
        split.addWidget(left)
        self.page = QWidget()
        self.layout = QVBoxLayout(self.page)
        split.addWidget(self.page)
        split.setSizes([280, 900])
        action = QAction("Сохранить", self)
        action.setShortcut(QKeySequence.StandardKey.Save)
        action.triggered.connect(self.save)
        self.addAction(action)
        self.statusBar().showMessage("Загрузка библиотеки…")
        self.refresh()

    def error(self, message: str):
        self.statusBar().showMessage(
            "Операция не выполнена. Несохранённый текст остаётся в редакторе."
        )
        QMessageBox.critical(self, "Не удалось выполнить операцию", message)

    def refresh(self, selected=None):
        self.setEnabled(False)

        def ready(catalog):
            self.catalog = catalog
            self.tree.blockSignals(True)
            self.tree.clear()
            universe_root = QTreeWidgetItem(self.tree, ["Вселенные"])
            work_root = QTreeWidgetItem(self.tree, ["Произведения"])
            universe_nodes = {}
            work_nodes = {}
            selected_item = None
            for kind, root, parents in (
                ("universe", universe_root, universe_nodes),
                ("work", work_root, work_nodes),
            ):
                for row in catalog[kind]:
                    node = QTreeWidgetItem(root, [row["title"]])
                    node.setData(0, Qt.ItemDataRole.UserRole, (kind, row["id"]))
                    parents[row["id"]] = node
                    if selected == (kind, row["id"]):
                        selected_item = node
            for kind, parent_key, parents in (
                ("article", "universe_id", universe_nodes),
                ("scene", "work_id", work_nodes),
            ):
                for row in catalog[kind]:
                    node = QTreeWidgetItem(parents[row[parent_key]], [row["title"]])
                    node.setData(0, Qt.ItemDataRole.UserRole, (kind, row["id"]))
                    if selected == (kind, row["id"]):
                        selected_item = node
            self.tree.expandAll()
            self.tree.setCurrentItem(selected_item)
            self.tree.blockSignals(False)
            if selected:
                self.load(selected)
            else:
                self.setEnabled(True)
                if self.selected is None:
                    self.welcome()
            self.statusBar().showMessage("Библиотека загружена")

        def failed(message):
            self.setEnabled(True)
            self.error(message)

        self.jobs.submit(self.library.catalog, ready, failed)

    def clear(self):
        self.loading = True
        self.fields = {}
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.loading = False

    def welcome(self):
        self.clear()
        self.layout.addWidget(QLabel("Ваша следующая история начинается здесь"))
        self.layout.addWidget(
            QLabel(
                "Создайте произведение или вселенную кнопкой «＋ Создать».\n"
                "Разрабатывать энциклопедию заранее необязательно."
            )
        )
        self.layout.addStretch()

    def choose(self, current, _previous):
        target = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if target and target != self.selected:
            self.guard(lambda: self.load(target))

    def guard(self, continuation):
        """Drain the editor before leaving it; errors keep the original editor visible."""
        if self.saving:
            QTimer.singleShot(50, lambda: self.guard(continuation))
            return
        if self.dirty:
            self.save(after=continuation, lock=True)
        else:
            continuation()

    def load(self, target):
        self.setEnabled(False)

        def ready(row):
            self.selected = target
            self.dirty = False
            self.render(target[0], row)
            self.setEnabled(True)

        def failed(message):
            self.setEnabled(True)
            self.error(message)

        self.jobs.submit(lambda: self.library.get(*target), ready, failed)

    def render(self, kind: str, row: dict):
        self.clear()
        self.loading = True
        header = QLabel(NAMES[kind])
        header.setObjectName("heading")
        self.layout.addWidget(header)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        self.layout.addWidget(form_widget)

        def line(key, label):
            widget = QLineEdit(str(row.get(key, "")))
            widget.textChanged.connect(self.changed)
            self.fields[key] = widget
            form.addRow(label, widget)

        line("title", "Название")
        if kind in ("article", "work"):
            line("kind", "Тип (можно свой)")
        if kind == "work":
            line("status", "Статус")
            combo = QComboBox()
            combo.addItem("Без вселенной", None)
            for universe in self.catalog["universe"]:
                combo.addItem(universe["title"], universe["id"])
            combo.setCurrentIndex(max(0, combo.findData(row["universe_id"])))
            combo.currentIndexChanged.connect(self.changed)
            self.fields["universe_id"] = combo
            form.addRow("Вселенная", combo)
        if kind == "article":
            row = dict(row, tags=", ".join(row["tags"]))
            line("tags", "Теги через запятую")
        if kind in ("universe", "article"):
            key = "settings" if kind == "universe" else "fields"
            widget = QLineEdit(json.dumps(row[key], ensure_ascii=False))
            widget.textChanged.connect(self.changed)
            self.fields[key] = widget
            form.addRow("Настройки JSON" if kind == "universe" else "Доп. поля JSON", widget)
        text_key = "content" if kind in ("article", "scene") else "description"
        self.editor = QPlainTextEdit(row[text_key])
        self.editor.setPlaceholderText("Начните писать…")
        self.editor.setMinimumHeight(220)
        self.fields[text_key] = self.editor
        self.editor.textChanged.connect(self.changed)
        self.layout.addWidget(self.editor, 1)
        self.counter = QLabel()
        self.layout.addWidget(self.counter)
        self.update_counter()
        buttons = QWidget()
        actions = QHBoxLayout(buttons)
        self.layout.addWidget(buttons)

        def button(label, callback):
            widget = QPushButton(label)
            widget.clicked.connect(callback)
            actions.addWidget(widget)

        button("Сохранить · Ctrl+S", self.save)
        if kind == "universe":
            button("Найти статью", self.search_dialog)
        if kind == "scene":
            button("↑ Раньше", lambda: self.guard(lambda: self.move(-1)))
            button("↓ Позже", lambda: self.guard(lambda: self.move(1)))
        actions.addStretch()
        button("Удалить", lambda: self.guard(self.delete_dialog))
        self.layout.addWidget(QLabel("Изменено: " + str(row["updated_at"])[:19] + " UTC"))
        self.loading = False

    def update_counter(self):
        self.counter.setText(f"Слов: {count_words(self.editor.toPlainText())}")

    def changed(self, *_args):
        if self.loading:
            return
        self.revision += 1
        self.dirty = True
        self.update_counter()
        self.statusBar().showMessage("Есть несохранённые изменения")
        if self.selected and self.selected[0] == "scene":
            self.timer.start()

    def values(self):
        values = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QPlainTextEdit):
                value = widget.toPlainText()
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
            else:
                value = widget.text()
            if key in ("settings", "fields"):
                value = json.loads(value)
            elif key == "tags":
                value = [tag.strip() for tag in value.split(",") if tag.strip()]
            values[key] = value
        return values

    def save(self, _checked=False, *, after=None, lock=False):
        self.timer.stop()
        if self.saving:
            if self.dirty:
                self.timer.start()
            return
        if not self.dirty or not self.selected:
            if after:
                after()
            return
        try:
            values = self.values()
        except (ValueError, TypeError) as error:
            self.error("Проверьте JSON дополнительных полей: " + str(error))
            return
        target, revision = self.selected, self.revision
        self.saving = True
        if lock:
            self.setEnabled(False)

        def success(_row):
            self.saving = False
            self.setEnabled(True)
            if self.selected == target and self.revision == revision:
                self.dirty = False
                for row in self.catalog.get(target[0], []):
                    if row["id"] == target[1]:
                        row.update(_row)
                iterator = self.tree.invisibleRootItem()

                def rename(node):
                    if node.data(0, Qt.ItemDataRole.UserRole) == target:
                        node.setText(0, _row["title"])
                    for index in range(node.childCount()):
                        rename(node.child(index))

                rename(iterator)
                self.statusBar().showMessage("Сохранено")
            elif self.selected and self.selected[0] == "scene":
                self.timer.start()
            if after:
                self.guard(after)

        def failure(message):
            self.saving = False
            self.setEnabled(True)
            self.error(message)

        self.jobs.submit(lambda: self.library.update(*target, values), success, failure)

    def create_dialog(self):
        self.guard(self._create_dialog)

    def _create_dialog(self):
        label, ok = QInputDialog.getItem(self, "Создать", "Объект", list(NAMES.values()), 0, False)
        if not ok:
            return
        kind = next(key for key, value in NAMES.items() if value == label)
        parent = None
        if kind in ("article", "scene", "work"):
            parent_kind = "work" if kind == "scene" else "universe"
            rows = self.catalog[parent_kind]
            choices = (["Без вселенной"] if kind == "work" else []) + [
                f"{row['title']} · #{row['id']}" for row in rows
            ]
            if not choices:
                self.error(
                    "Сначала создайте " + ("произведение" if kind == "scene" else "вселенную")
                )
                return
            choice, ok = QInputDialog.getItem(
                self, "Расположение", NAMES[parent_kind], choices, 0, False
            )
            if not ok:
                return
            index = choices.index(choice) - (1 if kind == "work" else 0)
            parent = rows[index]["id"] if index >= 0 else None
        title, ok = QInputDialog.getText(self, "Создать " + label.lower(), "Название")
        if ok:
            self.setEnabled(False)

            def success(row):
                self.setEnabled(True)
                self.refresh((kind, row["id"]))

            def failure(message):
                self.setEnabled(True)
                self.error(message)

            self.jobs.submit(lambda: self.library.create(kind, title, parent), success, failure)

    def delete_dialog(self):
        if not self.selected:
            return
        target = self.selected
        detail = {
            "universe": "Все её статьи будут удалены. Произведения сохранятся без вселенной.",
            "work": "Все сцены произведения будут удалены.",
        }.get(target[0], "")
        answer = QMessageBox.question(
            self,
            "Удалить объект?",
            "Удаление необратимо. " + detail,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.setEnabled(False)

            def success(_):
                self.setEnabled(True)
                self.selected = None
                self.refresh()

            def failure(message):
                self.setEnabled(True)
                self.error(message)

            self.jobs.submit(lambda: self.library.delete(*target), success, failure)

    def move(self, delta):
        self.setEnabled(False)
        target = self.selected

        def failed(message):
            self.setEnabled(True)
            self.error(message)

        self.jobs.submit(
            lambda: self.library.move_scene(target[1], delta),
            lambda _: self.refresh(target),
            failed,
        )

    def search_dialog(self):
        self.guard(self._search_dialog)

    def _search_dialog(self):
        target = self.selected
        query, ok = QInputDialog.getText(self, "Энциклопедия", "Название, текст или тег")
        if not ok:
            return

        def found(rows):
            if not rows:
                QMessageBox.information(self, "Поиск", "Статьи не найдены")
                return
            choices = [f"{row['title']} · #{row['id']}" for row in rows]
            choice, accepted = QInputDialog.getItem(
                self, "Результаты", "Открыть статью", choices, 0, False
            )
            if accepted:
                self.guard(lambda: self.load(("article", rows[choices.index(choice)]["id"])))

        self.jobs.submit(lambda: self.library.search(target[1], query), found, self.error)

    def show_settings(self):
        self.selected = None
        self.clear()
        self.layout.addWidget(QLabel("Настройки и данные"))
        self.layout.addWidget(QLabel("База данных: " + str(self.library.engine.url.database)))
        self.layout.addWidget(
            QLabel(
                "Все данные хранятся на этом компьютере.\n"
                "Резервная копия — SQLite; переносимый экспорт — JSON UTF-8."
            )
        )
        for export, label in ((False, "Создать резервную копию"), (True, "Экспортировать JSON")):
            button = QPushButton(label)
            button.clicked.connect(
                lambda _checked=False, export=export: self.file_operation(export)
            )
            self.layout.addWidget(button)
        self.layout.addStretch()

    def file_operation(self, export):
        suffix = ".json" if export else ".sqlite3"
        suggested = (
            Path(self.library.engine.url.database).parent
            / "backups"
            / (datetime.now().strftime("arhitektor-%Y%m%d-%H%M%S-%f") + suffix)
        )
        filename, _ = QFileDialog.getSaveFileName(self, "Сохранить данные", str(suggested))
        if filename:
            operation = self.library.export if export else self.library.backup
            self.jobs.submit(
                lambda: operation(Path(filename)),
                lambda path: QMessageBox.information(self, "Готово", f"Сохранено: {path}"),
                self.error,
            )

    def closeEvent(self, event):
        if self.closing:
            event.accept()
            return
        event.ignore()

        def finish():
            # Sentinel runs after every queued operation, so shutdown cannot block on disk I/O.
            self.setEnabled(False)

            def drained(_):
                self.closing = True
                self.jobs.shutdown()
                self.close()

            self.jobs.submit(lambda: None, drained, self.error)

        self.guard(finish)
