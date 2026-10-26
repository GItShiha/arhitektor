"""Editable contextual metadata without raw JSON inputs."""

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class FieldEditor(QWidget):
    changed = Signal()

    def __init__(self, fields: dict[str, Any], parent=None):
        super().__init__(parent)
        self.original = fields.copy()
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Поле", "Значение", "Тип"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(155)
        self.table.cellChanged.connect(lambda *_: self.changed.emit())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        add = QPushButton("＋ Поле")
        add.clicked.connect(self.add)
        remove = QPushButton("Удалить поле")
        remove.clicked.connect(self.remove)
        row.addWidget(add)
        row.addWidget(remove)
        layout.addLayout(row)
        for key, value in fields.items():
            self.add(key, value, notify=False)

    def add(self, key="", value="", notify=True):
        index = self.table.rowCount()
        self.table.insertRow(index)
        self.table.setItem(index, 0, QTableWidgetItem(str(key)))
        complex_value = isinstance(value, (dict, list))
        self.table.setItem(
            index,
            1,
            QTableWidgetItem(
                "Сложное значение · сохранится без изменений" if complex_value else str(value)
            ),
        )
        if complex_value:
            item = self.table.item(index, 1)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        types = QComboBox()
        for label, code in (
            ("Текст", "str"),
            ("Число", "number"),
            ("Да / нет", "bool"),
            ("Сложное", "complex"),
        ):
            types.addItem(label, code)
        selected = (
            "complex"
            if complex_value
            else "bool"
            if isinstance(value, bool)
            else ("number" if isinstance(value, (int, float)) else "str")
        )
        types.setCurrentIndex(types.findData(selected))
        types.setEnabled(not complex_value)
        types.currentIndexChanged.connect(lambda _: self.changed.emit())
        self.table.setCellWidget(index, 2, types)
        if notify:
            self.changed.emit()

    def remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.changed.emit()

    def read(self) -> dict[str, Any]:
        result = {}
        for row in range(self.table.rowCount()):
            key = self.table.item(row, 0).text().strip()
            if not key:
                raise ValueError("Укажите название дополнительного поля")
            if key in result:
                raise ValueError(f"Поле «{key}» повторяется")
            raw = self.table.item(row, 1).text().strip()
            kind = self.table.cellWidget(row, 2).currentData()
            if kind == "complex":
                result[key] = self.original[key]
            elif kind == "number":
                result[key] = float(raw) if "." in raw else int(raw)
            elif kind == "bool":
                result[key] = raw.casefold() in ("true", "да", "1", "yes")
            else:
                result[key] = raw
        return result


class PropertiesPanel(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(245)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 20, 18, 18)
        self.form = None
        self.fields: dict[str, QWidget] = {}

    def show_record(self, kind: str, row: dict, universes: list[dict]):
        self.clear()
        heading = QLabel("СВОЙСТВА")
        heading.setObjectName("eyebrow")
        self.layout.addWidget(heading)
        form_widget = QWidget()
        self.form = QFormLayout(form_widget)
        self.layout.addWidget(form_widget)
        self._static(
            "Объект",
            {
                "universe": "Вселенная",
                "article": "Статья",
                "work": "Произведение",
                "scene": "Сцена",
            }[kind],
        )
        if kind in ("article", "work"):
            self._line("kind", "Тип", row["kind"])
        if kind == "article":
            self._line("tags", "Теги", ", ".join(row["tags"]))
            self._editor("fields", "Доп. поля", row["fields"])
        if kind == "universe":
            self._editor("settings", "Настройки", row["settings"])
        if kind == "work":
            self._line("status", "Статус", row["status"])
            combo = QComboBox()
            combo.addItem("Без вселенной", None)
            for universe in universes:
                combo.addItem(universe["title"], universe["id"])
            combo.setCurrentIndex(max(0, combo.findData(row["universe_id"])))
            combo.currentIndexChanged.connect(lambda _: self.changed.emit())
            self.fields["universe_id"] = combo
            self.form.addRow("Вселенная", combo)
        if kind == "scene":
            self._static("Слов", str(row["word_count"]))
            self._static("Позиция", str(row["position"] + 1))
        self._static("Изменено", str(row["updated_at"])[:19] + " UTC")
        self.layout.addStretch()

    def _line(self, key, label, value):
        widget = QLineEdit(str(value))
        widget.textChanged.connect(lambda _: self.changed.emit())
        self.fields[key] = widget
        self.form.addRow(label, widget)

    def _editor(self, key, label, value):
        widget = FieldEditor(value)
        widget.changed.connect(self.changed)
        self.fields[key] = widget
        self.form.addRow(label, widget)

    def _static(self, label, value):
        widget = QLabel(value)
        widget.setWordWrap(True)
        self.form.addRow(label, widget)

    def clear(self):
        self.fields = {}
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
