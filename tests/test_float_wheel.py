import math

import pytest
from PySide6.QtCore import QLocale, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QComboBox, QDateEdit, QSpinBox, QVBoxLayout, QWidget

from arhitektor.ui.field_editor import ValueCard, scroll_area
from arhitektor.ui.numbers import DecimalSpinBox
from arhitektor.ui.templates import TypedValue


@pytest.mark.parametrize(
    "value, expected",
    [
        (1.25, "1,25"),
        (1.5, "1,5"),
        (1.0, "1"),
        (1.234567, "1,234567"),
        (0.0, "0"),
        (-1.25, "-1,25"),
    ],
)
def test_localized_shortest_float(qtbot, value, expected):
    editor = DecimalSpinBox()
    qtbot.addWidget(editor)
    editor.setLocale(QLocale("ru_RU"))
    editor.setValue(value)
    assert editor.text() == expected and editor.value() == value
    editor.lineEdit().selectAll()
    qtbot.keyClicks(editor.lineEdit(), expected)
    assert editor.value() == value


@pytest.mark.parametrize("value", [1.2345678901234567, 1e-20, 5e-324, 1.7976931348623157e308, -0.0])
def test_exact_binary64_roundtrip(qtbot, value):
    editor = DecimalSpinBox()
    qtbot.addWidget(editor)
    editor.setValue(value)
    assert editor.value().hex() == value.hex()
    editor.setLocale(QLocale("ru_RU"))
    editor.setValue(value)
    assert editor.value().hex() == value.hex()


def wheel(widget, delta=-120, pixel=False):
    center = widget.rect().center()
    event = QWheelEvent(
        QPointF(center),
        QPointF(widget.mapToGlobal(center)),
        QPoint(0, delta) if pixel else QPoint(),
        QPoint() if pixel else QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate if pixel else Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


def test_wheel_routes_to_panel_without_changing_controls(qtbot):
    content = QWidget()
    layout = QVBoxLayout(content)
    values = []
    for kind, value in (
        ("int", 12),
        ("float", 1.25),
        ("date", "2020-01-02"),
        ("bool", False),
        ("choice", "b"),
        ("reference", 2),
    ):
        field = TypedValue(
            {"name": kind, "kind": kind, "options": ["a", "b"]},
            value,
            [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}],
        )
        layout.addWidget(field)
        values.append(field)
    # Also cover dynamically added legacy controls and QDateEdit where still used by Qt.
    raw_controls = [QSpinBox(), QDateEdit(), QComboBox()]
    raw_controls[-1].addItems(["a", "b"])
    for control in raw_controls:
        layout.addWidget(control)
    scroll = scroll_area(content)
    qtbot.addWidget(scroll)
    scroll.resize(400, 220)
    scroll.show()
    qtbot.waitUntil(lambda: scroll.verticalScrollBar().maximum() > 0)
    for field in values:
        before = field.read()
        bar = scroll.verticalScrollBar()
        bar.setValue(0)
        field.editor.setFocus()
        wheel(field.editor)
        assert field.read() == before
        assert bar.value() > 0
        bar.setValue(0)
        if hasattr(field.editor, "lineEdit") and field.editor.lineEdit() is not None:
            wheel(field.editor.lineEdit(), delta=-30, pixel=True)
            assert field.read() == before and bar.value() > 0
    for control in raw_controls:
        scroll.verticalScrollBar().setValue(0)
        before = (
            control.date()
            if isinstance(control, QDateEdit)
            else control.currentIndex()
            if isinstance(control, QComboBox)
            else control.value()
        )
        wheel(control)
        after = (
            control.date()
            if isinstance(control, QDateEdit)
            else control.currentIndex()
            if isinstance(control, QComboBox)
            else control.value()
        )
        assert before == after and scroll.verticalScrollBar().value() > 0
    values[0].editor.stepUp()
    assert values[0].read() == 13
    combo = values[-2].editor
    combo.setCurrentIndex(1)
    assert values[-2].read() == "a"
    combo.showPopup()
    assert combo.view().isVisible()
    # The router deliberately leaves events for the open popup to Qt.
    event = QWheelEvent(
        QPointF(),
        QPointF(),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    assert not scroll._wheel_router.eventFilter(combo.view().viewport(), event)
    combo.hidePopup()


def test_float_save_reload_and_no_quantization(library, qtbot):
    universe = library.create("universe", "Мир")
    article = library.create("article", "Статья", universe["id"])
    value = 1.2345678901234567
    card = ValueCard("Дробь", value)
    qtbot.addWidget(card)
    assert not card.value_dirty and card.read() == value
    card.editor.setLocale(QLocale("ru_RU"))
    card.editor.setValue(value)
    card.editor.lineEdit().selectAll()
    qtbot.keyClicks(card.editor.lineEdit(), "1,2345678901234567")
    library.update("article", article["id"], {"fields": {"Дробь": card.read()}})
    library.engine.dispose()
    assert library.get("article", article["id"])["fields"]["Дробь"] == value
    empty = TypedValue({"name": "Дробь", "kind": "float"}, None, [])
    qtbot.addWidget(empty)
    assert empty.read() is None and empty.editor.text() == ""
    empty.editor.setValue(0)
    assert empty.read() == 0 and empty.read() is not None
    assert math.isfinite(empty.editor.maximum())


def test_open_popup_and_multiline_keep_their_wheel_handling(qtbot):
    from PySide6.QtWidgets import QPlainTextEdit

    content = QWidget()
    layout = QVBoxLayout(content)
    combo = QComboBox()
    combo.addItems([str(i) for i in range(100)])
    text = QPlainTextEdit("строка\n" * 100)
    layout.addWidget(combo)
    layout.addWidget(text)
    scroll = scroll_area(content)
    qtbot.addWidget(scroll)
    scroll.resize(350, 180)
    scroll.show()
    combo.showPopup()
    view = combo.view()
    qtbot.waitUntil(lambda: view.isVisible())
    before = view.verticalScrollBar().value()
    wheel(view.viewport())
    assert view.verticalScrollBar().value() > before
    combo.hidePopup()
    before = text.verticalScrollBar().value()
    wheel(text.viewport())
    assert text.verticalScrollBar().value() > before
