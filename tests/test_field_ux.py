import pytest
from PySide6.QtCore import QDate, QSettings, Qt
from PySide6.QtWidgets import QCheckBox

from arhitektor.ui.templates import TypedValue
from arhitektor.ui.window import MainWindow


@pytest.mark.parametrize("kind", ["text", "long", "int", "float", "date", "choice", "reference"])
def test_input_without_enable_and_clear(qtbot, kind):
    widget = TypedValue(
        {"name": "Тест", "kind": kind, "options": ["первый", "второй"]},
        None,
        [{"id": 8, "title": "Цель"}],
    )
    qtbot.addWidget(widget)
    widget.show()
    assert widget.editor.isEnabled() and widget.read() is None
    assert not widget.findChildren(QCheckBox)
    if kind == "text":
        widget.editor.setText("текст")
        expected = "текст"
    elif kind == "long":
        widget.editor.setPlainText("Отдельное свойство\nс текстом")
        expected = "Отдельное свойство\nс текстом"
    elif kind in ("int", "float"):
        widget.editor.setValue(2)
        expected = 2
    elif kind == "date":
        widget.editor.setDate(QDate(2001, 2, 3))
        expected = "2001-02-03"
    else:
        widget.editor.setCurrentIndex(1)
        expected = "первый" if kind == "choice" else 8
    assert widget.read() == expected
    widget.clear_button.click()
    assert widget.read() is None and widget.editor.isEnabled()


def test_none_zero_empty_and_boolean(qtbot):
    for value, index in ((None, 0), (True, 1), (False, 2)):
        widget = TypedValue({"name": "Флаг", "kind": "bool"}, value, [])
        qtbot.addWidget(widget)
        assert widget.editor.currentIndex() == index and widget.read() is value
        for new_value, new_index in ((False, 2), (True, 1), (None, 0)):
            widget.editor.setCurrentIndex(new_index)
            assert widget.read() is new_value
    text = TypedValue({"name": "Текст", "kind": "text"}, None, [])
    qtbot.addWidget(text)
    text.editor.setText("a")
    text.editor.clear()
    assert text.read() == ""
    text.clear_value()
    assert text.read() is None
    number = TypedValue({"name": "Число", "kind": "int"}, None, [])
    qtbot.addWidget(number)
    number.show()
    number.editor.lineEdit().selectAll()
    qtbot.keyClicks(number.editor.lineEdit(), "0")
    assert number.read() == 0 and number.read() is not None


def test_universe_filter_labels_and_restart(qtbot, library, monkeypatch, tmp_path):
    monkeypatch.setattr(
        "arhitektor.ui.window.QSettings",
        lambda *args: QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    one = library.create("universe", "Север")
    two = library.create("universe", "Юг")
    a = library.create("article", "Общее имя", one["id"])
    b = library.create("article", "Общее имя", two["id"])
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.open_section("Энциклопедия")
    root = window.tree.topLevelItem(0)
    assert root.childCount() == 2
    assert "Север" in root.child(0).text(0) and "Юг" in root.child(1).text(0)
    assert window.nav.templates_button.isVisible()
    window.nav.universe.setCurrentIndex(window.nav.universe.findData(two["id"]))
    root = window.tree.topLevelItem(0)
    assert root.childCount() == 1 and root.child(0).data(0, Qt.ItemDataRole.UserRole) == (
        "article",
        b["id"],
    )
    window.close()
    qtbot.waitUntil(lambda: window.closing)
    reopened = MainWindow(library)
    qtbot.addWidget(reopened)
    reopened.show()
    qtbot.waitUntil(lambda: bool(reopened.catalog) and reopened.isEnabled())
    assert reopened.nav.universe_id == two["id"]
    assert library.get("article", a["id"])["universe_id"] == one["id"]
    assert len(library.catalog()["article"]) == 2
    reopened.close()
    qtbot.waitUntil(lambda: reopened.closing)


def test_typed_value_save_without_enable_and_no_write_on_open(qtbot, library):
    from arhitektor.templates import Templates

    uid = library.create("universe", "Мир")["id"]
    target = library.create("article", "Цель", uid)
    template = Templates(library.engine).create_with_fields(
        uid,
        "Тест",
        [
            {"name": "Дата", "kind": "date"},
            {"name": "Флаг", "kind": "bool"},
            {"name": "Ссылка", "kind": "reference"},
            {"name": "Текст", "kind": "text"},
        ],
    )
    article = Templates(library.engine).create_article(uid, "Статья", template["id"])
    library.update("article", article["id"], {"fields": {"Старое": [None, "текст"]}})
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.navigate(("article", article["id"]))
    qtbot.waitUntil(lambda: window.selected == ("article", article["id"]) and window.isEnabled())
    assert not window.dirty
    assert library.get("article", article["id"])["fields"] == {"Старое": [None, "текст"]}
    keys = [d["id"] for d in template["definitions"]]
    controls = window.fields["fields"].typed
    controls[keys[0]].editor.setDate(QDate(2024, 2, 29))
    controls[keys[1]].editor.setCurrentIndex(2)
    controls[keys[2]].editor.setCurrentIndex(controls[keys[2]].editor.findData(target["id"]))
    controls[keys[3]].editor.setText("новый текст")
    window.save()
    qtbot.waitUntil(lambda: not window.dirty)
    row = library.get("article", article["id"])
    assert [row["fields"][k] for k in keys] == ["2024-02-29", False, target["id"], "новый текст"]
    assert row["fields"]["Старое"] == [None, "текст"]
    controls[keys[3]].clear_value()
    window.close()
    qtbot.waitUntil(lambda: window.closing)
    assert library.get("article", article["id"])["fields"][keys[3]] is None
