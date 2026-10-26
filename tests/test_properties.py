import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QLineEdit, QSpinBox

from arhitektor.ui.field_editor import ComplexFieldDialog, FieldEditor, GrowingTextEdit
from arhitektor.ui.numbers import DecimalSpinBox
from arhitektor.ui.window import MainWindow


def test_typed_cards_and_exact_roundtrip(qtbot):
    values = {
        "Короткий": "текст",
        "Длинный": "абзац\n" * 25,
        "Целый": 42,
        "Дробный": 1.2345678901234567,
        "Булево": True,
        "Вложенный": {"список": [None, False, 2**70]},
        "Пустой": None,
        "Большой": 2**70,
        "Пробелы": "  оставить  ",
    }
    fields = FieldEditor(values)
    qtbot.addWidget(fields)
    assert fields.read() == values
    for card, cls in zip(
        fields.cards,
        (QLineEdit, GrowingTextEdit, QSpinBox, DecimalSpinBox, QCheckBox),
        strict=False,
    ):
        assert isinstance(card.editor, cls)
        assert isinstance(card.kind, QComboBox)
    fields.cards[0].name.setPlainText("Новое название")
    fields.cards[0].editor.setText("изменено")
    fields.cards[2].editor.setValue(-9)
    fields.cards[3].editor.setValue(2.5)
    fields.cards[4].editor.setChecked(False)
    fields.remove(fields.cards[-1])
    result = fields.read()
    assert result["Новое название"] == "изменено"
    assert result["Целый"] == -9 and result["Дробный"] == 2.5
    assert result["Булево"] is False and "Пробелы" not in result
    assert result["Вложенный"] == values["Вложенный"]
    # A type change must read the old editor using its old type.
    fields.cards[0].kind.setCurrentIndex(fields.cards[0].kind.findData("int"))
    assert fields.read()["Новое название"] == 0


def test_complex_dialog_commit_and_cancel(qtbot):
    original = {"семья": ["Лев", None], "возраст": 20}
    dialog = ComplexFieldDialog(original)
    qtbot.addWidget(dialog)
    dialog.fields.cards[1].editor.setValue(21)
    dialog.reject()
    assert original["возраст"] == 20 and dialog.result_value == original
    accepted = ComplexFieldDialog(original)
    qtbot.addWidget(accepted)
    accepted.fields.cards[0].name.setPlainText("родные")
    accepted.fields.cards[1].editor.setValue(22)
    accepted.accept()
    assert accepted.result_value == {"родные": ["Лев", None], "возраст": 22}
    items = ComplexFieldDialog([False, 2, {"имя": "Лев"}])
    qtbot.addWidget(items)
    items.fields.cards[0].editor.setChecked(True)
    items.fields.remove(items.fields.cards[1])
    items.fields.add(value="ещё")
    items.accept()
    assert items.result_value == [True, {"имя": "Лев"}, "ещё"]


@pytest.mark.parametrize("kind,key", [("universe", "settings"), ("article", "fields")])
def test_property_changes_saved_on_navigation(qtbot, library, monkeypatch, kind, key):
    universe = library.create("universe", "Мир")
    record = universe if kind == "universe" else library.create("article", "Герой", universe["id"])
    library.update(kind, record["id"], {key: {"Год": 10, "Удалить": "x", "Сложное": [None, True]}})
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.navigate((kind, record["id"]))
    qtbot.waitUntil(lambda: window.selected == (kind, record["id"]) and window.isEnabled())
    fields = window.fields[key]
    fields.cards[0].name.setPlainText("Номер года")
    fields.cards[0].editor.setValue(11)

    def edit_list(dialog):
        dialog.fields.cards[1].editor.setChecked(False)
        dialog.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ComplexFieldDialog, "exec", edit_list)
    fields.cards[2].edit_complex()
    fields.remove(fields.cards[1])
    fields.add("Описание", "Длинный текст\n" * 20)
    window.open_section("Произведения")
    qtbot.waitUntil(lambda: window.selected is None and not window.dirty)
    saved = library.get(kind, record["id"])[key]
    assert saved == {"Номер года": 11, "Сложное": [None, False], "Описание": "Длинный текст\n" * 20}
    window.close()
    qtbot.waitUntil(lambda: window.closing)


def test_narrow_panel_scrolls_only_vertically(qtbot, library):
    universe = library.create("universe", "Мир")
    library.update(
        "universe",
        universe["id"],
        {
            "settings": {
                "Очень длинное название поля " * 5: "Строка с подробным описанием. " * 50,
                **{f"Поле {i}": i for i in range(8)},
            }
        },
    )
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.navigate(("universe", universe["id"]))
    qtbot.waitUntil(lambda: window.selected == ("universe", universe["id"]) and window.isEnabled())
    window.split.setSizes([240, 600, 330])
    qtbot.waitUntil(lambda: window.props.scroll.verticalScrollBar().maximum() > 0)
    scroll = window.props.scroll
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert scroll.widget().width() <= scroll.viewport().width()
    for card in window.fields["settings"].cards:
        assert card.width() <= scroll.viewport().width()
    first = window.fields["settings"].cards[0]
    qtbot.waitUntil(lambda: first.editor.height() > 96)
    assert first.name.document().size().height() <= first.name.viewport().height()
    assert first.editor.document().size().height() <= first.editor.viewport().height()
    window.close()
    qtbot.waitUntil(lambda: window.closing)


def test_duplicate_field_validation(qtbot):
    fields = FieldEditor({"Имя": "Лев"})
    qtbot.addWidget(fields)
    fields.add("Имя", "Ворон")
    with pytest.raises(ValueError, match="повторяется"):
        fields.read()
