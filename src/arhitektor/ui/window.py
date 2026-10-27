"""Main window: navigation, guarded transitions and serial persistence."""

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from arhitektor.relations import Relations
from arhitektor.services import Library, count_words
from arhitektor.templates import Templates
from arhitektor.ui.field_editor import scroll_area
from arhitektor.ui.jobs import Jobs
from arhitektor.ui.navigation import NavigationPanel
from arhitektor.ui.properties import FieldEditor, PropertiesPanel
from arhitektor.ui.relations import (
    DeleteRelationsDialog,
    RelatedObjects,
    RelationDialog,
    related_rows,
)
from arhitektor.ui.templates import TemplateDialog

NAMES = {"universe": "Вселенная", "article": "Статья", "work": "Произведение", "scene": "Сцена"}


class MainWindow(QMainWindow):
    def __init__(self, library: Library):
        super().__init__()
        self.library = library
        self.jobs = Jobs(self)
        self.selected: tuple[str, int] | None = None
        self.catalog: dict[str, list[dict[str, Any]]] = {}
        self.fields: dict[str, Any] = {}
        self.history: list[tuple[str, tuple[str, int] | None, int | None]] = []
        self.revision = 0
        self.dirty = self.saving = self.closing = self.loading = False
        self.focus_mode = False
        self.properties_before_focus = True
        self.view_section = "Обзор"
        self.view_universe = None
        self.settings = QSettings("Arhitektor", "Arhitektor")
        self.filter_restored = False
        self.setWindowTitle("Архитектор — мастерская писателя")
        self.resize(1340, 820)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(700)
        self.timer.timeout.connect(self.save)
        self.split = QSplitter()
        self.setCentralWidget(self.split)
        self.nav = NavigationPanel()
        self.nav.target_requested.connect(lambda target: self.navigate(target))
        self.nav.section_requested.connect(self.open_section)
        self.nav.universe_requested.connect(self.open_universe)
        self.nav.create_requested.connect(self.create_dialog)
        self.nav.settings_requested.connect(lambda: self.transition(self.show_settings))
        self.nav.back_requested.connect(self.back)
        self.nav.templates_requested.connect(lambda: self.guard(self.manage_templates))
        self.split.addWidget(self.nav)
        self.page = QWidget()
        outer = QVBoxLayout(self.page)
        outer.setContentsMargins(28, 18, 28, 22)
        toolbar = QHBoxLayout()
        self.crumbs = QLabel("Библиотека")
        self.crumbs.setObjectName("eyebrow")
        toolbar.addWidget(self.crumbs, 1)
        self.props_toggle = QPushButton("Скрыть свойства")
        self.props_toggle.clicked.connect(self.toggle_properties)
        toolbar.addWidget(self.props_toggle)
        self.focus_button = QPushButton("Режим письма")
        self.focus_button.clicked.connect(self.toggle_focus)
        toolbar.addWidget(self.focus_button)
        outer.addLayout(toolbar)
        self.body = QWidget()
        self.layout = QVBoxLayout(self.body)
        self.layout.setContentsMargins(0, 8, 0, 0)
        self.body_scroll = scroll_area(self.body)
        outer.addWidget(self.body_scroll, 1)
        self.split.addWidget(self.page)
        self.props = PropertiesPanel()
        self.props.changed.connect(self.changed)
        self.props.template_requested.connect(
            lambda identifier: self.guard(lambda: self.assign_template(identifier))
        )
        self.props.open_requested.connect(lambda identifier: self.navigate(("article", identifier)))
        self.split.addWidget(self.props)
        self.split.setStretchFactor(1, 1)
        self.normal_splitter_state = None
        state = self.settings.value("splitter")
        if state:
            self.split.restoreState(state)
        else:
            self.split.setSizes([260, 790, 290])
        self.props.setVisible(self.settings.value("properties_visible", True, type=bool))
        self.props_toggle.setText(
            "Скрыть свойства" if not self.props.isHidden() else "Показать свойства"
        )
        action = QAction("Сохранить", self)
        action.setShortcut(QKeySequence.StandardKey.Save)
        action.triggered.connect(self.save)
        self.addAction(action)
        self.refresh()
        from arhitektor.ui.updates import Updates

        self.updates = Updates(self)

    @property
    def tree(self):  # Compatibility for callers using the former tree attribute.
        return self.nav.tree

    def error(self, message):
        self.statusBar().showMessage("Операция не выполнена; изменения остаются в редакторе")
        QMessageBox.critical(self, "Не удалось выполнить операцию", message)

    def refresh(self, selected=None):
        self.setEnabled(False)

        def ready(catalog):
            self.catalog = catalog
            self.nav.update_universes(catalog["universe"])
            if not self.filter_restored:
                uid = self.settings.value("universe_filter", "")
                uid = int(uid) if str(uid).isdigit() else None
                self.nav.universe.blockSignals(True)
                self.nav.universe.setCurrentIndex(max(0, self.nav.universe.findData(uid)))
                self.nav.universe.blockSignals(False)
                self.filter_restored = True
            if selected:
                self.nav.select_section(self.nav.section_for(selected[0]))
            self.nav.populate(catalog, selected)
            if selected:
                self.load(selected)
            else:
                self.setEnabled(True)
                if self.selected is None:
                    self.show_section_page()
            self.statusBar().showMessage("Библиотека загружена")

        def failed(message):
            self.setEnabled(True)
            self.error(message)

        self.jobs.submit(self.library.catalog, ready, failed)

    def clear(self):
        self.loading = True
        self.fields = {}
        self.props.clear()
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.loading = False

    def heading(self, title, subtitle=""):
        label = QLabel(title)
        label.setObjectName("heading")
        self.layout.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("subtitle")
            sub.setWordWrap(True)
            self.layout.addWidget(sub)

    def welcome(self):
        self.show_section_page()

    def show_section_page(self):
        self.selected = None
        self.clear()
        section = self.nav.section
        self.view_section = section
        self.view_universe = self.nav.universe_id
        self.crumbs.setText("Библиотека  /  " + section)
        if section == "Обзор":
            uid = self.nav.universe_id
            if uid is not None:
                self.load(("universe", uid))
                return
            self.heading(
                "Мастерская писателя", "Выберите вселенную или начните работу над произведением."
            )
            self.layout.addWidget(
                QLabel(
                    f"Вселенных: {len(self.catalog.get('universe', []))}   ·   "
                    f"Произведений: {len(self.catalog.get('work', []))}"
                )
            )
        else:
            self.heading(section, "Выберите объект в списке слева или создайте новый.")
            if section == "Произведения":
                rows = self.catalog.get("work", [])
                if self.nav.universe_id is not None:
                    rows = [r for r in rows if r["universe_id"] == self.nav.universe_id]
                self.layout.addWidget(QLabel(f"Произведений: {len(rows)}"))
        self.layout.addStretch()

    def _location(self):
        return self.nav.section, self.selected, self.nav.universe_id

    def transition(self, action):
        previous = self._location()

        def proceed():
            self.history.append(previous)
            action()

        self.guard(proceed)

    def navigate(self, target, remember=True):
        if target == self.selected:
            return

        def proceed():
            if remember:
                self.history.append(self._location())
            self.nav.select_section(self.nav.section_for(target[0]))
            self.nav.populate(self.catalog, target)
            self.load(target)

        self.guard(proceed)

    def open_section(self, section):
        self.nav.select_section(self.view_section)

        def proceed():
            self.history.append(self._location())
            self.nav.select_section(section)
            self.nav.populate(self.catalog)
            self.show_section_page()

        self.guard(proceed)

    def open_universe(self, identifier):
        self.nav.universe.blockSignals(True)
        self.nav.universe.setCurrentIndex(max(0, self.nav.universe.findData(self.view_universe)))
        self.nav.universe.blockSignals(False)

        def proceed():
            self.nav.universe.blockSignals(True)
            self.nav.universe.setCurrentIndex(max(0, self.nav.universe.findData(identifier)))
            self.nav.universe.blockSignals(False)
            self.history.append(self._location())
            self.nav.populate(self.catalog)
            self.show_section_page()

        self.guard(proceed)

    def back(self):
        if not self.history:
            return

        def proceed():
            section, target, uid = self.history.pop()
            self.nav.universe.blockSignals(True)
            self.nav.universe.setCurrentIndex(max(0, self.nav.universe.findData(uid)))
            self.nav.universe.blockSignals(False)
            self.nav.select_section(section)
            self.nav.populate(self.catalog, target)
            if target:
                self.load(target)
            else:
                self.show_section_page()

        self.guard(proceed)

    def guard(self, continuation):
        if self.saving:
            QTimer.singleShot(50, lambda: self.guard(continuation))
        elif self.dirty:
            self.save(after=continuation, lock=True)
        else:
            continuation()

    def load(self, target):
        self.setEnabled(False)

        def ready(row):
            self.selected = target
            self.dirty = False
            self.nav.select_target(target)
            self.render(target[0], row)
            self.setEnabled(True)

        def failed(message):
            self.setEnabled(True)
            self.error(message)

        self.jobs.submit(lambda: self.library.get(*target), ready, failed)

    def _line(self, key, value, placeholder=""):
        widget = QLineEdit(str(value))
        widget.setPlaceholderText(placeholder)
        widget.setObjectName(key)
        widget.textChanged.connect(self.changed)
        self.fields[key] = widget
        self.layout.addWidget(widget)
        return widget

    def _button(self, text, callback, layout):
        button = QPushButton(text)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def render(self, kind, row):
        self.clear()
        self.loading = True
        self.props.show_record(
            kind,
            row,
            self.catalog["universe"],
            self.catalog.get("template", []),
            self.catalog["article"],
        )
        self.fields.update(self.props.fields)
        self.view_section = self.nav.section
        self.view_universe = self.nav.universe_id
        self.crumbs.setText(f"{self.nav.section}  /  {row['title']}")
        if kind == "universe":
            self.heading("Обзор вселенной", "Один мир может объединять несколько произведений.")
        elif kind == "article":
            self.heading("Страница энциклопедии", row["kind"])
        elif kind == "work":
            self.heading("Рукопись", "Выберите сцену слева и продолжайте писать.")
        else:
            work = next((w for w in self.catalog["work"] if w["id"] == row["work_id"]), None)
            self.heading("Сцена", work["title"] if work else "")
        self._line("title", row["title"], "Название")
        text_key = "content" if kind in ("article", "scene") else "description"
        if kind == "article":
            self.layout.addWidget(QLabel("Основное описание"))
        self.editor = QPlainTextEdit(row[text_key])
        self.editor.setPlaceholderText("Начните писать…")
        self.editor.setObjectName("manuscript" if kind == "scene" else "content")
        self.editor.textChanged.connect(self.changed)
        self.fields[text_key] = self.editor
        if kind == "article":
            self.editor.setMinimumHeight(220)
        self.layout.addWidget(self.editor, 1)
        self.counter = QLabel()
        self.layout.addWidget(self.counter)
        self.update_counter()
        if kind == "article":
            related = RelatedObjects(row["id"], self.catalog)
            related.open_requested.connect(
                lambda identifier: self.navigate(("article", identifier))
            )
            related.create_requested.connect(lambda: self.guard(self.create_relation))
            related.remove_requested.connect(lambda: self.guard(self.delete_relations))
            self.layout.addWidget(related)
            summary = QWidget()
            summary_layout = QVBoxLayout(summary)
            summary_layout.addWidget(QLabel(f"Связей: {len(related.model.rows)}"))
            self._button(
                "К списку связей",
                lambda: self.body_scroll.ensureWidgetVisible(related.search),
                summary_layout,
            )
            self.props.layout.insertWidget(self.props.layout.count() - 1, summary)
        if kind == "universe":
            articles = [a for a in self.catalog["article"] if a["universe_id"] == row["id"]]
            works = [w for w in self.catalog["work"] if w["universe_id"] == row["id"]]
            self.layout.addWidget(
                QLabel(f"Статей: {len(articles)}    ·    Произведений: {len(works)}")
            )
            recent = sorted([*articles, *works], key=lambda r: r["updated_at"], reverse=True)[:5]
            self.layout.addWidget(QLabel("Недавно изменены"))
            if recent:
                for item in recent:
                    target_kind = "article" if "fields" in item else "work"
                    self._button(
                        item["title"],
                        lambda _=False, k=target_kind, i=item["id"]: self.navigate((k, i)),
                        self.layout,
                    )
            else:
                self.layout.addWidget(QLabel("Пока нет статей и произведений"))
            actions = QHBoxLayout()
            self._button("＋ Статья", lambda: self.create_dialog("article", row["id"]), actions)
            self._button(
                "＋ Персонаж", lambda: self.create_dialog("article", row["id"], "Персонаж"), actions
            )
            self._button("＋ Произведение", lambda: self.create_dialog("work", row["id"]), actions)
            self.layout.addLayout(actions)
        if kind == "work":
            scenes = [s for s in self.catalog["scene"] if s["work_id"] == row["id"]]
            self.layout.addWidget(QLabel(f"Сцен: {len(scenes)}"))
            actions = QHBoxLayout()
            for scene in scenes:
                self._button(
                    scene["title"],
                    lambda _=False, i=scene["id"]: self.navigate(("scene", i)),
                    actions,
                )
            self._button("＋ Сцена", lambda: self.create_dialog("scene", row["id"]), actions)
            self.layout.addLayout(actions)
        actions = QHBoxLayout()
        self._button("Сохранить · Ctrl+S", self.save, actions)
        if kind == "scene":
            self._button("↑ Раньше", lambda: self.guard(lambda: self.move(-1)), actions)
            self._button("↓ Позже", lambda: self.guard(lambda: self.move(1)), actions)
        actions.addStretch()
        self._button("Удалить", lambda: self.guard(self.delete_dialog), actions)
        self.layout.addLayout(actions)
        self.loading = False

    def assign_template(self, identifier):
        row = next(a for a in self.catalog["article"] if a["id"] == self.selected[1])
        self.run_relation(
            lambda: Templates(self.library.engine).assign(row["universe_id"], row["id"], identifier)
        )

    def manage_templates(self):
        universes = self.catalog["universe"]
        if not universes:
            self.error("Сначала создайте вселенную")
            return
        uid = self.nav.universe_id
        if uid is None:
            labels = [f"{u['title']} · #{u['id']}" for u in universes]
            chosen, ok = QInputDialog.getItem(self, "Типы и шаблоны", "Вселенная", labels, 0, False)
            if not ok:
                return
            uid = universes[labels.index(chosen)]["id"]
        templates = sorted(
            [t for t in self.catalog["template"] if t["universe_id"] == uid],
            key=lambda t: t["position"],
        )
        labels = [
            f"{t['title']} · статей: {sum(a.get('template_id') == t['id'] for a in self.catalog['article'])}"
            for t in templates
        ] + ["＋ Новый тип"]
        chosen, ok = QInputDialog.getItem(self, "Типы и шаблоны", "Тип", labels, 0, False)
        if not ok:
            return
        index = labels.index(chosen)
        template = (
            templates[index]
            if index < len(templates)
            else {"title": "Новый тип", "definitions": [], "position": len(templates)}
        )
        dialog = TemplateDialog(
            template, [a for a in self.catalog["article"] if a["universe_id"] == uid], self
        )
        if not dialog.exec():
            return
        position, ok = QInputDialog.getInt(
            self, "Порядок типов", "Позиция (с нуля)", template["position"], 0, 10000
        )
        if not ok:
            return
        definitions = [editor.read() for editor in dialog.definitions]
        title = dialog.title.text()

        def operation():
            service = Templates(self.library.engine)
            if "id" in template:
                return service.save(uid, template["id"], title, definitions, position)
            # Validate and create atomically using the same service operation.
            return service.create_with_fields(uid, title, definitions, position)

        self.setEnabled(False)

        def done(_):
            self.selected = None
            self.refresh()

        def failed(message):
            self.setEnabled(True)
            self.error(message)

        self.jobs.submit(operation, done, failed)

    def create_relation(self):
        source_id = self.selected[1]
        source = next(row for row in self.catalog["article"] if row["id"] == source_id)
        candidates = [
            row
            for row in self.catalog["article"]
            if row["universe_id"] == source["universe_id"] and row["id"] != source_id
        ]
        dialog = RelationDialog(candidates, self)
        if dialog.exec():
            target, label, reverse = dialog.values()
            self.run_relation(
                lambda: Relations(self.library.engine).create(source_id, target, label, reverse)
            )

    def delete_relations(self):
        article_id = self.selected[1]
        dialog = DeleteRelationsDialog(related_rows(article_id, self.catalog), self)

        def remove(identifiers):
            if not identifiers or dialog.busy:
                return
            dialog.set_busy(True)

            def done(_):
                # Publish the entire committed change at once, without a second DB read.
                removed = set(identifiers)
                self.catalog["relation"] = [
                    r for r in self.catalog["relation"] if r["id"] not in removed
                ]
                row = next(a for a in self.catalog["article"] if a["id"] == article_id)
                self.render("article", row)
                dialog.accept()
                self.statusBar().showMessage(f"Удалено связей: {len(removed)}")

            self.jobs.submit(
                lambda: Relations(self.library.engine).delete_many(article_id, identifiers),
                done,
                dialog.show_error,
            )

        dialog.delete_requested.connect(remove)
        dialog.exec()
        dialog.deleteLater()

    def run_relation(self, operation):
        target = self.selected
        self.setEnabled(False)

        def failed(message):
            self.setEnabled(True)
            self.error(message)

        self.jobs.submit(operation, lambda _: self.refresh(target), failed)

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
            elif isinstance(widget, FieldEditor):
                value = widget.read()
            elif hasattr(widget, "currentData"):
                value = widget.currentData()
            else:
                value = widget.text()
            if key == "tags":
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
        except (ValueError, TypeError, KeyError) as error:
            self.error("Проверьте дополнительные поля: " + str(error))
            return
        target, revision = self.selected, self.revision
        self.saving = True
        if lock:
            self.setEnabled(False)

        def success(row):
            self.saving = False
            self.setEnabled(True)
            if self.selected == target and self.revision == revision:
                self.dirty = False
                for entry in self.catalog[target[0]]:
                    if entry["id"] == target[1]:
                        entry.update(row)
                self.nav.update_universes(self.catalog["universe"])
                self.nav.populate(self.catalog, target)
                self.crumbs.setText(f"{self.nav.section}  /  {row['title']}")
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

    def create_dialog(self, kind=None, parent=None, preset_kind=None):
        self.guard(lambda: self._create_dialog(kind, parent, preset_kind))

    def _create_dialog(self, kind, parent, preset_kind):
        if not kind:
            choices = list(NAMES.values())
            label, ok = QInputDialog.getItem(self, "Создать", "Объект", choices, 0, False)
            if not ok:
                return
            kind = next(key for key, value in NAMES.items() if value == label)
        if kind == "article" and parent is None:
            parent = self.nav.universe_id
        if kind in ("article", "scene", "work") and parent is None:
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
        title, ok = QInputDialog.getText(self, "Создать " + NAMES[kind].lower(), "Название")
        if not ok:
            return
        chosen_template = None
        if kind == "article":
            templates = [t for t in self.catalog.get("template", []) if t["universe_id"] == parent]
            if templates:
                labels = [t["title"] for t in templates]
                selected, accepted = QInputDialog.getItem(
                    self, "Новая статья", "Тип", labels, 0, False
                )
                if not accepted:
                    return
                chosen_template = templates[labels.index(selected)]["id"]
        self.setEnabled(False)

        def success(row):
            def done(_=None):
                self.setEnabled(True)
                self.refresh((kind, row["id"]))

            if chosen_template is not None:
                done()
            elif preset_kind:
                self.jobs.submit(
                    lambda: self.library.update(kind, row["id"], {"kind": preset_kind}),
                    done,
                    self.error,
                )
            else:
                done()

        def failure(message):
            self.setEnabled(True)
            self.error(message)

        def operation():
            if chosen_template is not None:
                return Templates(self.library.engine).create_article(parent, title, chosen_template)
            return self.library.create(kind, title, parent)

        self.jobs.submit(operation, success, failure)

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
        if not target or target[0] != "universe":
            return
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
                self.navigate(("article", rows[choices.index(choice)]["id"]))

        self.jobs.submit(lambda: self.library.search(target[1], query), found, self.error)

    def show_settings(self):
        self.selected = None
        self.clear()
        self.crumbs.setText("Библиотека  /  Настройки")
        self.heading("Настройки и данные", "Локальное хранение без обязательных облачных сервисов.")
        self.layout.addWidget(QLabel("База данных: " + str(self.library.engine.url.database)))
        self._button("Типы и шаблоны", self.manage_templates, self.layout)
        self._button("Обновления", self.updates.open_settings, self.layout)
        for export, label in ((False, "Создать резервную копию"), (True, "Экспортировать JSON")):
            self._button(label, lambda _=False, e=export: self.file_operation(e), self.layout)
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

    def toggle_properties(self):
        if not self.props.isHidden():
            self.normal_splitter_state = self.split.saveState()
        self.props.setVisible(self.props.isHidden())
        if not self.props.isHidden() and self.normal_splitter_state:
            self.split.restoreState(self.normal_splitter_state)
        self.props_toggle.setText(
            "Показать свойства" if self.props.isHidden() else "Скрыть свойства"
        )

    def toggle_focus(self):
        if not self.focus_mode:
            self.properties_before_focus = not self.props.isHidden()
            self.normal_splitter_state = self.split.saveState()
        self.focus_mode = not self.focus_mode
        self.nav.setVisible(not self.focus_mode)
        self.props.setVisible(False if self.focus_mode else self.properties_before_focus)
        if not self.focus_mode and self.normal_splitter_state:
            self.split.restoreState(self.normal_splitter_state)
        self.props_toggle.setEnabled(not self.focus_mode)
        self.focus_button.setText("Выйти из режима письма" if self.focus_mode else "Режим письма")
        if self.focus_mode:
            self.editor.setFocus() if hasattr(self, "editor") else None

    def closeEvent(self, event):
        if self.closing:
            state = (
                self.split.saveState()
                if not self.focus_mode and not self.props.isHidden()
                else (self.normal_splitter_state or self.split.saveState())
            )
            self.settings.setValue(
                "universe_filter", self.nav.universe_id if self.nav.universe_id is not None else ""
            )
            self.settings.setValue("splitter", state)
            self.settings.setValue(
                "properties_visible",
                self.properties_before_focus if self.focus_mode else not self.props.isHidden(),
            )
            event.accept()
            return
        event.ignore()

        def finish():
            self.setEnabled(False)

            def drained(_):
                try:
                    action = getattr(self, "close_action", None)
                    if action:
                        self.close_action = None
                        action()
                except OSError:
                    self.setEnabled(True)
                    self.error("Не удалось запустить установщик. Приложение остаётся открытым.")
                    return
                self.updates.shutdown()
                self.closing = True
                self.jobs.shutdown()
                self.close()

            self.jobs.submit(lambda: None, drained, self.error)

        self.guard(finish)
