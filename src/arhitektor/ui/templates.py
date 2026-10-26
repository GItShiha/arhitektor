"""Template controls extend the existing vertical property editor."""

from copy import deepcopy

from PySide6.QtCore import QDate, QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from arhitektor.templates import KINDS
from arhitektor.ui.field_editor import FieldEditor, GrowingTextEdit, ValueCard, scroll_area
from arhitektor.ui.nullable import EmptyDateEdit, EmptyDoubleSpinBox, EmptySpinBox


class TypedValue(QWidget):
    changed = Signal()
    open_requested = Signal(int)

    def __init__(self, definition, value, articles, parent=None):
        super().__init__(parent)
        self.definition = definition
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        label = QLabel(
            definition["name"]
            + ("\nДополнительное многострочное поле" if definition["kind"] == "long" else "")
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        self.present = value is not None
        kind = definition["kind"]
        self.kind = kind
        if kind == "date":
            self.editor = EmptyDateEdit()
            self.editor.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
            self.editor.setCalendarPopup(True)
            self.editor.setDisplayFormat("dd.MM.yyyy")
            if value is not None:
                self.editor.setDate(QDate.fromString(value, "yyyy-MM-dd"))
            self.editor.dateChanged.connect(self.mark_edited)
            self.editor.lineEdit().textEdited.connect(self.mark_edited)
        elif kind in ("choice", "reference", "bool"):
            self.editor = QComboBox()
            self.editor.setMinimumWidth(0)
            self.editor.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            self.editor.addItem("Не указано", None)
            if kind == "bool":
                self.editor.addItem("Да", True)
                self.editor.addItem("Нет", False)
            elif kind == "choice":
                for option in definition.get("options", []):
                    self.editor.addItem(option, option)
            else:
                for article in articles:
                    self.editor.addItem(article["title"], article["id"])
            index = self.editor.findData(value)
            if value is not None and index < 0:
                self.editor.addItem("Недоступное значение", value)
                index = self.editor.count() - 1
            self.editor.setCurrentIndex(max(0, index))
            self.editor.currentIndexChanged.connect(self.mark_edited)
        else:
            sample = {"text": "", "long": "", "int": 0, "float": 0.0, "bool": False}[kind]
            initial = value if value is not None else sample
            if kind == "float":
                initial = float(initial)
            self.card = ValueCard("", initial)
            if kind in ("text", "long"):
                self.card.kind.setCurrentIndex(self.card.kind.findData(kind))
            self.editor = self.card.editor
            if isinstance(self.editor, (QSpinBox, QDoubleSpinBox)):
                old = self.editor
                editor = EmptyDoubleSpinBox() if isinstance(old, QDoubleSpinBox) else EmptySpinBox()
                if isinstance(old, QDoubleSpinBox):
                    editor.setDecimals(old.decimals())
                editor.setRange(old.minimum(), old.maximum())
                editor.setValue(old.value())
                self.card.layout.removeWidget(old)
                old.deleteLater()
                self.editor = self.card.editor = editor
                editor.valueChanged.connect(self.card.edit_value)
            self.card.layout.removeWidget(self.editor)
            self.editor.setParent(self)
            self.card.changed.connect(self.mark_edited)
            if hasattr(self.editor, "lineEdit"):
                self.editor.lineEdit().textEdited.connect(self.mark_edited)
            self.card.hide()
        if value is None and hasattr(self.editor, "set_empty"):
            self.editor.set_empty()
        layout.addWidget(self.editor)
        self.clear_button = QPushButton("Очистить")
        self.clear_button.clicked.connect(self.clear_value)
        layout.addWidget(self.clear_button)
        if kind == "reference":
            button = QPushButton("Перейти к статье")
            button.clicked.connect(
                lambda: (
                    self.open_requested.emit(self.editor.currentData())
                    if self.present and self.editor.currentData() is not None
                    else None
                )
            )
            layout.addWidget(button)

    def mark_edited(self, *_args):
        self.present = (
            self.editor.currentData() is not None
            if self.kind in ("bool", "choice", "reference")
            else True
        )
        if hasattr(self.editor, "set_empty"):
            self.editor.set_empty(False)
        if hasattr(self, "card"):
            self.card.value_dirty = True
        self.changed.emit()

    def clear_value(self):
        with QSignalBlocker(self.editor):
            if self.kind in ("bool", "choice", "reference"):
                self.editor.setCurrentIndex(0)
            elif self.kind == "date" or hasattr(self.editor, "set_empty"):
                self.editor.set_empty()
            elif hasattr(self.editor, "setPlainText"):
                self.editor.setPlainText("")
            else:
                self.editor.setText("")
        self.present = False
        self.changed.emit()

    def read(self):
        if not self.present:
            return None
        if self.kind == "date":
            if not self.editor.text():
                return None
            if not self.editor.date().isValid():
                raise ValueError("Введите дату в формате дд.мм.гггг")
            return self.editor.date().toString("yyyy-MM-dd")
        if self.kind in ("choice", "reference", "bool"):
            return self.editor.currentData()
        return self.card.read()


class TemplateFields(FieldEditor):
    open_requested = Signal(int)

    def __init__(self, values, template, all_templates, articles):
        definitions = {d["id"]: d for t in all_templates for d in t["definitions"]}
        active = [d for d in template["definitions"] if d.get("active", True)] if template else []
        keys = {d["id"] for d in active}
        extras = {k: v for k, v in values.items() if k not in keys}
        super().__init__({k: v for k, v in extras.items() if k not in definitions})
        self.typed = {}
        for definition in active + [
            dict(definitions[k], name=definitions[k]["name"] + " (вне шаблона)")
            for k in extras
            if k in definitions
        ]:
            key = definition["id"]
            widget = TypedValue(definition, values.get(key), articles)
            widget.changed.connect(self.changed)
            widget.open_requested.connect(self.open_requested)
            self.typed[key] = widget
            self.layout.insertWidget(len(self.typed) - 1, widget)

    def read(self):
        result = super().read()
        if set(result) & self.typed.keys():
            raise ValueError("Имя дополнительного поля совпало с идентификатором шаблона")
        result.update({key: widget.read() for key, widget in self.typed.items()})
        return result


class DefinitionEditor(QWidget):
    def __init__(self, definition, articles):
        super().__init__()
        self.original = deepcopy(definition)
        self.articles = articles
        layout = QVBoxLayout(self)
        self.name = QLineEdit(definition.get("name", "Новое поле"))
        layout.addWidget(QLabel("Название"))
        layout.addWidget(self.name)
        self.kind = QComboBox()
        for code, label in KINDS.items():
            self.kind.addItem(label, code)
        self.kind.setCurrentIndex(max(0, self.kind.findData(definition.get("kind", "text"))))
        layout.addWidget(self.kind)
        self.options = GrowingTextEdit("\n".join(definition.get("options", [])))
        self.options.setPlaceholderText("Варианты выбора — по одному на строку")
        layout.addWidget(self.options)
        self.default = QCheckBox("Использовать значение по умолчанию")
        self.default.setChecked("default" in definition)
        layout.addWidget(self.default)
        self.value = None
        self.rebuild()
        self.kind.currentIndexChanged.connect(self.rebuild)
        self.options.textChanged.connect(self.rebuild)

    def rebuild(self, *_args):
        if self.value:
            self.layout().removeWidget(self.value)
            self.value.deleteLater()
        definition = {
            "name": "Значение по умолчанию",
            "kind": self.kind.currentData(),
            "options": self.options.toPlainText().splitlines(),
        }
        initial = (
            self.original.get("default")
            if self.original.get("kind") == definition["kind"]
            else None
        )
        self.value = TypedValue(definition, initial, self.articles)
        self.layout().addWidget(self.value)

    def read(self):
        result = dict(
            self.original,
            name=self.name.text(),
            kind=self.kind.currentData(),
            options=self.options.toPlainText().splitlines(),
        )
        result.pop("default", None)
        if self.default.isChecked():
            result["default"] = self.value.read()
        return result


class TemplateDialog(QDialog):
    def __init__(self, template, articles, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Типы и шаблоны")
        self.resize(650, 700)
        layout = QVBoxLayout(self)
        self.title = QLineEdit(template["title"])
        layout.addWidget(QLabel("Название типа"))
        layout.addWidget(self.title)
        self.content = QWidget()
        self.rows = QVBoxLayout(self.content)
        self.definitions = []
        layout.addWidget(scroll_area(self.content))
        self.articles = articles
        for definition in template["definitions"]:
            if definition.get("active", True):
                self.add(definition)
        add = QPushButton("＋ Поле")
        add.clicked.connect(lambda: self.add({}))
        layout.addWidget(add)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def add(self, definition):
        editor = DefinitionEditor(definition, self.articles)
        self.definitions.append(editor)
        self.rows.addWidget(editor)
        actions = QHBoxLayout()
        for text, callback in (
            ("↑", lambda: self.move(editor, -1)),
            ("↓", lambda: self.move(editor, 1)),
            ("Удалить поле", lambda: self.remove(editor)),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            actions.addWidget(button)
        editor.layout().addLayout(actions)

    def move(self, editor, delta):
        index = self.definitions.index(editor)
        other = index + delta
        if 0 <= other < len(self.definitions):
            self.definitions[index], self.definitions[other] = (
                self.definitions[other],
                self.definitions[index],
            )
            for row in self.definitions:
                self.rows.removeWidget(row)
            for row in self.definitions:
                self.rows.addWidget(row)

    def remove(self, editor):
        self.definitions.remove(editor)
        self.rows.removeWidget(editor)
        editor.deleteLater()
