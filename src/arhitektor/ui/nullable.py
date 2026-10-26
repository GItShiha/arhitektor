"""Empty display for Qt spin editors, independent of their internal stepping value.

No sentinel is reserved in the valid numeric/date range. TypedValue owns the actual
optional model value. Opening or leaving an untouched empty control cannot set it.
"""

from PySide6.QtCore import QDate, QSignalBlocker, Signal
from PySide6.QtWidgets import (
    QCalendarWidget,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arhitektor.ui.numbers import DecimalSpinBox


class EmptyDisplay:
    _empty = False

    def set_empty(self, empty=True):
        self._empty = empty
        if empty:
            self.lineEdit().clear()
        self.update()

    def stepBy(self, steps):
        if self._empty:
            with QSignalBlocker(self):
                self.setValue(0)
        self._empty = False
        super().stepBy(steps)

    def focusOutEvent(self, event):
        if self._empty and not self.lineEdit().text():
            # Qt interprets empty text on focus loss. That is display maintenance,
            # not an explicit edit, and must not produce a model change.
            with QSignalBlocker(self):
                super().focusOutEvent(event)
            self.lineEdit().clear()
        else:
            super().focusOutEvent(event)


class EmptySpinBox(EmptyDisplay, QSpinBox):
    def textFromValue(self, value):
        return "" if self._empty else super().textFromValue(value)

    def setValue(self, value):
        was_empty = self._empty
        self._empty = False
        previous = self.value()
        super().setValue(value)
        if was_empty and previous == self.value():
            self.lineEdit().setText(self.textFromValue(self.value()))
            self.valueChanged.emit(self.value())


class EmptyDoubleSpinBox(EmptyDisplay, DecimalSpinBox):
    def textFromValue(self, value):
        return "" if self._empty else super().textFromValue(value)

    def setValue(self, value):
        was_empty = self._empty
        self._empty = False
        previous = self._value
        super().setValue(value)
        if was_empty and previous == self.value():
            self.lineEdit().setText(self.textFromValue(self.value()))
            self.valueChanged.emit(self.value())


class EmptyDateEdit(QWidget):
    """An optional date has no internal default: only valid text or a calendar choice.

    QDateEdit coerces empty text to its internal date. A line edit plus a native
    calendar avoids that coercion while keeping both keyboard and calendar input.
    """

    dateChanged = Signal(QDate)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("propertyWheelControl", True)
        self._format = "dd.MM.yyyy"
        self._line = QLineEdit(self)
        self._line.setPlaceholderText("Не указано · дд.мм.гггг")
        self._line.setMinimumWidth(0)
        self._line.textEdited.connect(self._edited)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._line, 1)
        button = QToolButton()
        button.setText("▦")
        button.setToolTip("Выбрать дату")
        button.setAccessibleName("Открыть календарь")
        button.clicked.connect(self.open_calendar)
        layout.addWidget(button)
        self.popup = QDialog(self)
        self.popup.setWindowTitle("Выберите дату")
        popup_layout = QVBoxLayout(self.popup)
        self.calendar = QCalendarWidget()
        self.calendar.setDateRange(QDate(1, 1, 1), QDate(9999, 12, 31))
        self.calendar.clicked.connect(self.choose_date)
        popup_layout.addWidget(self.calendar)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.rejected.connect(self.popup.reject)
        popup_layout.addWidget(buttons)

    def _edited(self, text):
        date = QDate.fromString(text, self._format)
        if date.isValid():
            self.dateChanged.emit(date)

    def choose_date(self, date):
        self.setDate(date)
        self.popup.accept()

    def open_calendar(self):
        date = self.date()
        if date.isValid():
            self.calendar.setSelectedDate(date)
        self.popup.open()

    def set_empty(self, empty=True):
        if empty:
            self._line.clear()

    def lineEdit(self):
        return self._line

    def calendarWidget(self):
        return self.calendar

    def setDateRange(self, minimum, maximum):
        self.calendar.setDateRange(minimum, maximum)

    def setCalendarPopup(self, _enabled):
        pass

    def setDisplayFormat(self, pattern):
        self._format = pattern

    def text(self):
        return self._line.text()

    def date(self):
        return QDate.fromString(self.text(), self._format)

    def setDate(self, date):
        if date.isValid():
            self._line.setText(date.toString(self._format))
            self.dateChanged.emit(date)
