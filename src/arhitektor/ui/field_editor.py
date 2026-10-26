"""Vertical, typed property cards and a spacious editor for nested JSON values."""

from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from arhitektor.ui.numbers import DecimalSpinBox
from arhitektor.ui.wheel import route_property_wheels


def scroll_area(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(content)
    route_property_wheels(scroll)
    return scroll


class GrowingTextEdit(QTextEdit):
    def __init__(self, text: str, parent=None, minimum_height=96):
        super().__init__(parent)
        self.minimum_height = minimum_height
        self.setAcceptRichText(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setPlainText(text)
        self.document().documentLayout().documentSizeChanged.connect(self.adjust_height)
        self.adjust_height()

    def adjust_height(self, *_args):
        self.setFixedHeight(max(self.minimum_height, int(self.document().size().height()) + 22))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.adjust_height()


class ValueCard(QWidget):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, key: str, value: Any, parent=None):
        super().__init__(parent)
        self.setObjectName("propertyCard")
        self.original = deepcopy(value)
        self.value_dirty = False
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.addWidget(QLabel("Название поля"))
        self.name = GrowingTextEdit(key, minimum_height=48)
        self.name.setMinimumWidth(0)
        self.name.textChanged.connect(self.changed)
        self.layout.addWidget(self.name)
        self.layout.addWidget(QLabel("Тип значения"))
        self.kind = QComboBox()
        for label, code in (
            ("Короткий текст", "text"),
            ("Длинный текст", "long"),
            ("Целое число", "int"),
            ("Дробное число", "float"),
            ("Да / нет", "bool"),
            ("Объект / список", "complex"),
            ("Не задано", "null"),
        ):
            self.kind.addItem(label, code)
        code = (
            "null"
            if value is None
            else "bool"
            if isinstance(value, bool)
            else "int"
            if isinstance(value, int)
            else "float"
            if isinstance(value, float)
            else "complex"
            if isinstance(value, (dict, list))
            else "long"
            if "\n" in value or len(value) > 80
            else "text"
        )
        self.kind.setCurrentIndex(self.kind.findData(code))
        self.layout.addWidget(self.kind)
        self.layout.addWidget(QLabel("Значение"))
        self.editor = None
        self.make_editor(code, value)
        self.kind.currentIndexChanged.connect(self.change_type)
        remove = QPushButton("Удалить поле")
        remove.clicked.connect(lambda: self.removed.emit(self))
        self.layout.addWidget(remove)

    def edit_value(self, *_args):
        self.value_dirty = True
        self.changed.emit()

    def make_editor(self, code: str, value: Any):
        if self.editor is not None:
            self.layout.removeWidget(self.editor)
            self.editor.deleteLater()
        if code == "text":
            editor = QLineEdit(str(value))
            editor.setMinimumWidth(0)
            editor.textChanged.connect(self.edit_value)
        elif code == "long":
            editor = GrowingTextEdit(str(value))
            editor.textChanged.connect(self.edit_value)
        elif code in ("int", "float"):
            # Exceptional integers outside Qt's range retain their exact decimal representation.
            if code == "int" and not -(2**31) <= value < 2**31:
                editor = QLineEdit(str(value))
                editor.textChanged.connect(self.edit_value)
            elif code == "int":
                editor = QSpinBox()
                editor.setRange(-(2**31), 2**31 - 1)
                editor.setValue(value)
                editor.valueChanged.connect(self.edit_value)
            else:
                editor = DecimalSpinBox()
                editor.setRange(-1.7976931348623157e308, 1.7976931348623157e308)
                editor.setValue(value)
                editor.valueChanged.connect(self.edit_value)
            editor.setMinimumWidth(0)
            editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        elif code == "bool":
            editor = QCheckBox("Да")
            editor.setChecked(value)
            editor.toggled.connect(self.edit_value)
        elif code == "complex":
            editor = QPushButton("Открыть редактор…")
            editor.clicked.connect(self.edit_complex)
        else:
            editor = QLabel("Значение не задано")
            editor.setWordWrap(True)
        self.editor = editor
        self.editor_kind = code
        # Value precedes the remove button even after changing its type.
        self.layout.insertWidget(min(self.layout.count(), 5), editor)

    def change_type(self):
        code = self.kind.currentData()
        previous = self.read()
        value = {
            "text": str(previous) if previous is not None else "",
            "long": str(previous) if previous is not None else "",
            "int": 0,
            "float": 0.0,
            "bool": False,
            "complex": {},
            "null": None,
        }[code]
        self.original = value
        self.value_dirty = False
        self.make_editor(code, value)
        self.changed.emit()

    def read(self) -> Any:
        if not self.value_dirty:
            return deepcopy(self.original)
        if isinstance(self.editor, QCheckBox):
            return self.editor.isChecked()
        if isinstance(self.editor, (QSpinBox, DecimalSpinBox)):
            return self.editor.value()
        if isinstance(self.editor, QTextEdit):
            return self.editor.toPlainText()
        if isinstance(self.editor, QLineEdit):
            return int(self.editor.text()) if self.editor_kind == "int" else self.editor.text()
        return deepcopy(self.original)

    def edit_complex(self):
        dialog = ComplexFieldDialog(self.original, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.original = dialog.result_value
            self.value_dirty = False
            self.changed.emit()


class FieldEditor(QWidget):
    changed = Signal()

    def __init__(self, fields: dict[str, Any], parent=None):
        super().__init__(parent)
        self.cards: list[ValueCard] = []
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        add = QPushButton("＋ Добавить поле")
        add.clicked.connect(lambda: self.add())
        self.layout.addWidget(add)
        for key, value in fields.items():
            self.add(key, value, notify=False)

    def add(self, key="", value="", notify=True) -> ValueCard:
        card = ValueCard(key, value)
        card.changed.connect(self.changed)
        card.removed.connect(self.remove)
        self.cards.append(card)
        self.layout.insertWidget(self.layout.count() - 1, card)
        if notify:
            self.changed.emit()
        return card

    def remove(self, card: ValueCard):
        self.cards.remove(card)
        self.layout.removeWidget(card)
        card.deleteLater()
        self.changed.emit()

    def read(self) -> dict[str, Any]:
        result = {}
        for card in self.cards:
            key = card.name.toPlainText().strip()
            if not key:
                raise ValueError("Укажите название дополнительного поля")
            if key in result:
                raise ValueError(f"Поле «{key}» повторяется")
            result[key] = card.read()
        return result


class ComplexFieldDialog(QDialog):
    """Edit dictionaries and lists recursively, without a raw JSON editor."""

    def __init__(self, value: dict | list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование сложного поля")
        self.resize(740, 640)
        self.setMinimumWidth(580)
        self.is_list = isinstance(value, list)
        self.result_value = deepcopy(value)
        layout = QVBoxLayout(self)
        hint = QLabel(
            "Элементы списка идут сверху вниз; названия служат подписями."
            if self.is_list
            else "Изменяйте поля объекта. Вложенные объекты открываются отдельно."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.fields = FieldEditor(
            {str(i): v for i, v in enumerate(value)} if self.is_list else value
        )
        layout.addWidget(scroll_area(self.fields), 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        try:
            self.result_value = (
                [card.read() for card in self.fields.cards] if self.is_list else self.fields.read()
            )
        except ValueError as error:
            QMessageBox.warning(self, "Проверьте поля", str(error))
            return
        super().accept()
