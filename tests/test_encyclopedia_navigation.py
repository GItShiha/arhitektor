from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog

from arhitektor.templates import Templates
from arhitektor.ui.navigation import SECTIONS, NavigationPanel
from arhitektor.ui.window import MainWindow


def setup_catalog(library):
    world = library.create("universe", "Север")
    service = Templates(library.engine)
    template = service.create(world["id"], "Пользовательский тип")
    article = service.create_article(world["id"], "Цель", template["id"])
    library.update("article", article["id"], {"content": "Найди текст", "tags": ["метка"]})
    library.create("article", "Старая статья", world["id"])
    return world, template, article


def test_dynamic_empty_legacy_names_and_search(qtbot, library):
    world, template, article = setup_catalog(library)
    other = library.create("universe", "Юг")
    Templates(library.engine).create(other["id"], template["title"])
    nav = NavigationPanel()
    qtbot.addWidget(nav)
    assert len(SECTIONS) == 3
    nav.update_universes(library.catalog()["universe"])
    nav.select_section("Энциклопедия")
    nav.populate(library.catalog())
    assert nav.tree.topLevelItemCount() == 2
    key = ("category", world["id"], template["id"], "")
    assert nav.categories[key]["rows"][0]["id"] == article["id"]
    assert ("category", world["id"], None, "Персонаж") in nav.categories
    assert any(not group["rows"] for group in nav.categories.values())
    nav.select_target(("article", article["id"]))
    selected = nav.tree.currentItem()
    for query in ("НАЙДИ", "МЕТКА"):
        nav.search.setText(query)
        assert not selected.isHidden() and nav.tree.currentItem() is selected
        assert nav.tree.topLevelItem(1).isHidden()
    nav.search.clear()
    assert not nav.tree.topLevelItem(1).isHidden()
    service = Templates(library.engine)
    service.save(world["id"], template["id"], "Новое имя", [], 0)
    nav.populate(library.catalog())
    assert nav.categories[key]["title"] == "Новое имя"


def test_category_guard_back_create_and_expansion(qtbot, library, monkeypatch):
    world, template, article = setup_catalog(library)
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog) and window.isEnabled())
    window.open_section("Энциклопедия")
    key = ("category", world["id"], template["id"], "")
    window.navigate(key)
    assert window.category == key and window.selected is None
    window.navigate(("article", article["id"]))
    qtbot.waitUntil(lambda: window.selected == ("article", article["id"]) and window.isEnabled())
    window.editor.setPlainText("Сохрани перед категорией")
    window.back()
    qtbot.waitUntil(lambda: window.category == key and window.isEnabled())
    assert library.get("article", article["id"])["content"] == "Сохрани перед категорией"
    monkeypatch.setattr(QInputDialog, "getText", lambda *a: ("Новая статья", True))
    window.create_dialog()
    qtbot.waitUntil(lambda: window.selected is not None and window.isEnabled())
    created = library.get(*window.selected)
    assert created["template_id"] == template["id"] and created["universe_id"] == world["id"]
    nodes = [i for i in window.nav.items() if i.data(0, Qt.ItemDataRole.UserRole) == key]
    nodes[0].setExpanded(False)
    window.nav.populate(window.catalog)
    assert not next(
        i for i in window.nav.items() if i.data(0, Qt.ItemDataRole.UserRole) == key
    ).isExpanded()
    window.close()
    qtbot.waitUntil(lambda: window.closing)


def test_empty_category_and_template_order(qtbot, library):
    from PySide6.QtWidgets import QLabel

    world, _template, _ = setup_catalog(library)
    service = Templates(library.engine)
    empty = service.create(world["id"], "Пустой тип")
    service.save(world["id"], empty["id"], "Пустой тип", [], 0)
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog) and window.isEnabled())
    window.open_section("Энциклопедия")
    key = ("category", world["id"], empty["id"], "")
    window.navigate(key)
    assert window.selected is None and window.category == key
    assert any("пока нет статей" in label.text() for label in window.body.findChildren(QLabel))
    assert not window.nav.categories[key]["rows"]
    window.close()
    qtbot.waitUntil(lambda: window.closing)
