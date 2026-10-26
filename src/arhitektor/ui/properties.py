"""Editable contextual metadata without raw JSON inputs."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from arhitektor.ui.field_editor import FieldEditor, scroll_area
from arhitektor.ui.templates import TemplateFields


class PropertiesPanel(QWidget):
    changed = Signal()
    template_requested = Signal(int)
    open_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(330)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        self.layout = QVBoxLayout(content)
        self.layout.setContentsMargins(14, 18, 14, 18)
        self.scroll = scroll_area(content)
        outer.addWidget(self.scroll)
        self.form = None
        self.fields: dict[str, QWidget] = {}

    def show_record(self, kind: str, row: dict, universes: list[dict], templates=(), articles=()):
        self.clear()
        heading = QLabel("СВОЙСТВА")
        heading.setObjectName("eyebrow")
        self.layout.addWidget(heading)
        form_widget = QWidget()
        self.form = QFormLayout(form_widget)
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
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
        if kind == "work":
            self._line("kind", "Тип", row["kind"])
        if kind == "article":
            self._line("tags", "Теги", ", ".join(row["tags"]))
            available = sorted(
                [t for t in templates if t["universe_id"] == row["universe_id"]],
                key=lambda t: t["position"],
            )
            combo = QComboBox()
            combo.setMinimumWidth(0)
            combo.addItem(row["kind"] + " (текущий)", None)
            for template in available:
                combo.addItem(template["title"], template["id"])
            combo.setCurrentIndex(max(0, combo.findData(row.get("template_id"))))
            combo.currentIndexChanged.connect(
                lambda _: (
                    self.template_requested.emit(combo.currentData())
                    if combo.currentData() is not None
                    else None
                )
            )
            self.form.addRow("Тип", combo)
            template = next((t for t in available if t["id"] == row.get("template_id")), None)
            widget = TemplateFields(
                row["fields"],
                template,
                available,
                [a for a in articles if a["universe_id"] == row["universe_id"]],
            )
            widget.changed.connect(self.changed)
            widget.open_requested.connect(self.open_requested)
            self.fields["fields"] = widget
            self.form.addRow("Поля", widget)
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
