from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

from arhitektor.ui.properties import FieldEditor
from arhitektor.ui.window import MainWindow


def wait_selected(qtbot, window, target):
    qtbot.waitUntil(lambda: window.selected == target and window.isEnabled())


def test_sections_back_and_guarded_text(qtbot, library):
    universe = library.create("universe", "Север")
    article = library.create("article", "Герой", universe["id"])
    library.update("article", article["id"], {"content": "Старый текст"})
    work = library.create("work", "Роман", universe["id"])
    scene = library.create("scene", "Глава", work["id"])
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.nav.universe.setCurrentIndex(window.nav.universe.findData(universe["id"]))
    wait_selected(qtbot, window, ("universe", universe["id"]))
    assert any("Статей: 1" in w.text() for w in window.body.findChildren(type(window.crumbs)))
    window.nav.sections.setCurrentItem(
        window.nav.sections.findItems("Энциклопедия", Qt.MatchFlag.MatchExactly)[0]
    )
    qtbot.waitUntil(lambda: window.nav.section == "Энциклопедия")
    window.navigate(("article", article["id"]))
    wait_selected(qtbot, window, ("article", article["id"]))
    window.editor.setPlainText("Обновлённый текст")
    window.nav.sections.setCurrentItem(
        window.nav.sections.findItems("Произведения", Qt.MatchFlag.MatchExactly)[0]
    )
    qtbot.waitUntil(lambda: window.nav.section == "Произведения" and not window.dirty)
    assert library.get("article", article["id"])["content"] == "Обновлённый текст"
    window.navigate(("scene", scene["id"]))
    wait_selected(qtbot, window, ("scene", scene["id"]))
    window.back()
    qtbot.waitUntil(lambda: window.selected is None and window.nav.section == "Произведения")
    window.close()
    qtbot.waitUntil(lambda: window.closing)


def test_fields_preserve_nested_and_edit_without_json(qtbot, library):
    universe = library.create("universe", "Мир")
    article = library.create("article", "Описание", universe["id"])
    library.update("article", article["id"], {"fields": {"Возраст": 20, "Семья": {"брат": "Лев"}}})
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.navigate(("article", article["id"]))
    wait_selected(qtbot, window, ("article", article["id"]))
    fields = window.fields["fields"]
    assert isinstance(fields, FieldEditor)
    fields.table.setItem(0, 1, QTableWidgetItem("21"))
    fields.add("Прозвище", "Ворон")
    window.save()
    qtbot.waitUntil(lambda: not window.dirty)
    assert library.get("article", article["id"])["fields"] == {
        "Возраст": 21,
        "Семья": {"брат": "Лев"},
        "Прозвище": "Ворон",
    }
    window.close()
    qtbot.waitUntil(lambda: window.closing)


def test_panels_and_saved_widths(qtbot, library, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    monkeypatch.setattr(
        "arhitektor.ui.window.QSettings",
        lambda *args: QSettings(str(tmp_path / "ui.ini"), QSettings.Format.IniFormat),
    )
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.split.setSizes([310, 620, 350])
    widths = window.split.sizes()
    window.toggle_properties()
    assert window.props.isHidden()
    window.toggle_properties()
    assert not window.props.isHidden()
    window.toggle_focus()
    assert window.nav.isHidden() and window.props.isHidden()
    window.toggle_focus()
    assert not window.nav.isHidden() and not window.props.isHidden()
    window.close()
    qtbot.waitUntil(lambda: window.closing)
    reopened = MainWindow(library)
    qtbot.addWidget(reopened)
    reopened.show()
    qtbot.waitUntil(lambda: bool(reopened.catalog))
    assert all(abs(a - b) < 25 for a, b in zip(reopened.split.sizes(), widths, strict=True))
    reopened.close()
    qtbot.waitUntil(lambda: reopened.closing)
