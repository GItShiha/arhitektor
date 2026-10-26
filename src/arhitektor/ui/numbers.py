"""Locale-aware binary64 editor without fixed-decimal quantization."""

import math
import re
import sys

from PySide6.QtCore import QLocale, Signal
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QAbstractSpinBox


class DecimalSpinBox(QAbstractSpinBox):
    valueChanged = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._minimum, self._maximum = -sys.float_info.max, sys.float_info.max
        self.lineEdit().textEdited.connect(self._edited)
        self.editingFinished.connect(self._finish)
        self.lineEdit().setText(self.textFromValue(self._value))

    def textFromValue(self, value):
        # Python repr is the shortest decimal string which round-trips to binary64.
        text = repr(float(value))
        text = text.removesuffix(".0")
        return text.replace(".", self.locale().decimalPoint())

    def _parse(self, text):
        locale = QLocale(self.locale())
        locale.setNumberOptions(locale.numberOptions() | QLocale.NumberOption.RejectGroupSeparator)
        value, valid = locale.toDouble(text)
        if not valid or not math.isfinite(value) or not self._minimum <= value <= self._maximum:
            raise ValueError("Введите корректное дробное число в допустимом диапазоне")
        return value

    def validate(self, text, position):
        try:
            self._parse(text)
            state = QValidator.State.Acceptable
        except ValueError:
            separator = re.escape(self.locale().decimalPoint())
            pattern = rf"[+-]?\d*(?:{separator}\d*)?(?:[eE][+-]?\d*)?"
            state = (
                QValidator.State.Intermediate
                if re.fullmatch(pattern, text)
                else QValidator.State.Invalid
            )
        return state, text, position

    def _edited(self, text):
        try:
            self._value = self._parse(text)
        except ValueError:
            return
        self.valueChanged.emit(self._value)

    def _finish(self):
        if getattr(self, "_empty", False):
            return
        try:
            self.setValue(self._parse(self.lineEdit().text()))
        except ValueError:
            # Keep invalid input available for correction; saving reports the error.
            pass

    def value(self):
        return self._parse(self.lineEdit().text())

    def setValue(self, value):
        value = float(value)
        if not math.isfinite(value) or not self._minimum <= value <= self._maximum:
            raise ValueError("Число вне допустимого диапазона")
        changed = value != self._value
        self._value = value
        self.lineEdit().setText(self.textFromValue(value))
        if changed:
            self.valueChanged.emit(value)

    def minimum(self):
        return self._minimum

    def maximum(self):
        return self._maximum

    def setRange(self, minimum, maximum):
        self._minimum, self._maximum = minimum, maximum

    def stepBy(self, steps):
        self.setValue(max(self._minimum, min(self._maximum, self._value + steps)))

    def stepEnabled(self):
        flags = QAbstractSpinBox.StepEnabledFlag.StepNone
        if self._value < self._maximum:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepUpEnabled
        if self._value > self._minimum:
            flags |= QAbstractSpinBox.StepEnabledFlag.StepDownEnabled
        return flags
