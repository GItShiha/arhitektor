import json
import sqlite3
from pathlib import Path

import pytest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QLabel

from arhitektor.infrastructure.database import open_database
from arhitektor.services import Library
from arhitektor.templates import Templates
from arhitektor.ui.templates import TypedValue
from arhitektor.ui.window import MainWindow


@pytest.mark.parametrize("kind, value", [("int", 123), ("float", 3.5), ("date", "2024-02-29")])
def test_empty_display_focus_and_explicit_values(qtbot, kind, value):
    widget = TypedValue({"name": "Поле", "kind": kind}, value, [])
    qtbot.addWidget(widget)
    widget.show()
    widget.clear_button.click()
    assert widget.read() is None and widget.editor.text() == ""
    widget.editor.setFocus()
    widget.clear_button.setFocus()
    qtbot.wait(10)
    assert widget.read() is None and widget.editor.text() == ""
    if kind == "date":
        widget.editor.setDate(QDate(2000, 1, 1))
        assert widget.read() == "2000-01-01" and widget.editor.text()
    else:
        widget.editor.lineEdit().selectAll()
        qtbot.keyClicks(widget.editor.lineEdit(), "0")
        assert widget.read() == 0 and widget.read() is not None
    widget.clear_value()
    assert widget.editor.text() == "" and widget.read() is None
    if kind != "date":
        widget.editor.stepUp()
        assert widget.read() is not None and widget.editor.text()


@pytest.mark.parametrize(
    "kind", ["bool", "choice", "reference", "text", "long", "date", "int", "float"]
)
def test_no_duplicate_null_labels(qtbot, kind):
    widget = TypedValue({"name": "Поле", "kind": kind, "options": ["Вариант"]}, None, [])
    qtbot.addWidget(widget)
    assert not [label for label in widget.findChildren(QLabel) if label.text() == "Не указано"]
    assert widget.read() is None
    if kind in ("bool", "choice", "reference"):
        assert widget.editor.currentText() == "Не указано"


def test_clear_and_restart_record_json_null_in_sqlite(qtbot, library):
    uid = library.create("universe", "Мир")["id"]
    template = Templates(library.engine).create_with_fields(
        uid,
        "Тест",
        [
            {"name": "Число", "kind": "int", "default": 42},
            {"name": "Доля", "kind": "float", "default": 1.5},
            {"name": "Дата", "kind": "date", "default": "2024-02-29"},
        ],
    )
    article = Templates(library.engine).create_article(uid, "Статья", template["id"])
    keys = [d["id"] for d in template["definitions"]]

    def open_window():
        window = MainWindow(library)
        qtbot.addWidget(window)
        window.show()
        qtbot.waitUntil(lambda: bool(window.catalog))
        window.navigate(("article", article["id"]))
        qtbot.waitUntil(
            lambda: window.selected == ("article", article["id"]) and window.isEnabled()
        )
        return window

    def raw():
        with sqlite3.connect(library.engine.url.database) as conn:
            return json.loads(
                conn.execute("SELECT fields FROM articles WHERE id=?", (article["id"],)).fetchone()[
                    0
                ]
            )

    window = open_window()
    for widget in window.fields["fields"].typed.values():
        widget.clear_button.click()
        assert widget.editor.text() == ""
    window.save()
    qtbot.waitUntil(lambda: not window.dirty)
    assert [raw()[k] for k in keys] == [None, None, None]
    window.close()
    qtbot.waitUntil(lambda: window.closing)
    library.engine.dispose()
    engine = open_database(Path(library.engine.url.database))
    assert Library(engine).get("article", article["id"])["fields"] == dict.fromkeys(keys)
    engine.dispose()
    reopened = open_window()
    controls = reopened.fields["fields"].typed
    date_editor = controls[keys[2]].editor
    assert date_editor.text() == "" and not reopened.dirty
    # Open and dismiss the real Qt popup without selecting a date.
    date_editor.open_calendar()
    qtbot.keyClick(date_editor.calendarWidget(), Qt.Key.Key_Escape)
    assert controls[keys[2]].read() is None and not reopened.dirty
    assert raw()[keys[2]] is None
    date_editor.calendarWidget().clicked.emit(QDate(2023, 5, 6))
    controls[keys[0]].editor.setValue(0)
    reopened.save()
    qtbot.waitUntil(lambda: not reopened.dirty)
    assert raw()[keys[0]] == 0 and raw()[keys[0]] is not None
    assert raw()[keys[2]] == "2023-05-06"
    controls[keys[2]].clear_button.click()
    reopened.close()
    qtbot.waitUntil(lambda: reopened.closing)
    assert raw()[keys[2]] is None


def test_date_keyboard_input_after_clear(qtbot):
    widget = TypedValue({"name": "Дата", "kind": "date"}, None, [])
    qtbot.addWidget(widget)
    widget.show()
    widget.editor.lineEdit().setFocus()
    qtbot.keyClicks(widget.editor.lineEdit(), "15.03.2021")
    qtbot.keyClick(widget.editor, Qt.Key.Key_Tab)
    assert widget.read() == "2021-03-15"
