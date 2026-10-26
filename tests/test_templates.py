import pytest

from arhitektor.infrastructure.database import open_database
from arhitektor.relations import Relations
from arhitektor.services import Library
from arhitektor.templates import Templates


def test_template_lifecycle_and_restore(library, tmp_path):
    uid = library.create("universe", "Мир")["id"]
    service = Templates(library.engine)
    definitions = [
        {
            "name": name,
            "kind": kind,
            "default": value,
            "options": ["активна", "закрыта"] if kind == "choice" else [],
        }
        for name, kind, value in [
            ("Коротко", "text", "текст"),
            ("История", "long", "строка\nстрока"),
            ("Численность", "int", 12),
            ("Доля", "float", 2.5),
            ("Тайно", "bool", True),
            ("Дата", "date", "2020-02-29"),
            ("Статус", "choice", "активна"),
        ]
    ]
    template = service.create_with_fields(uid, "Спецслужба", definitions)
    article = library.create("article", "Служба", uid)
    library.update("article", article["id"], {"fields": {"Старое поле": [1, None]}})
    service.assign(uid, article["id"], template["id"])
    fields = library.get("article", article["id"])["fields"]
    assert fields[template["definitions"][2]["id"]] == 12
    updated = template["definitions"]
    updated[2]["name"] = "Количество сотрудников"
    service.save(uid, template["id"], "Спецслужба", updated, 0)
    assert library.get("article", article["id"])["fields"] == fields
    service.save(uid, template["id"], "Службы", updated[:2], 1)
    assert library.get("article", article["id"])["fields"] == fields
    assert library.get("article", article["id"])["kind"] == "Службы"
    other = service.create(uid, "Другой")
    service.assign(uid, article["id"], other["id"])
    assert library.get("article", article["id"])["fields"] == fields
    backup = library.backup(tmp_path / "copy.sqlite3")
    restored = open_database(backup)
    assert Library(restored).get("article", article["id"])["fields"] == fields
    assert len(Templates(restored).list(uid)) == len(service.list(uid))
    restored.dispose()
    import json

    exported = library.export(tmp_path / "export.json")
    assert json.loads(exported.read_text())["data"]["template"]


def test_references_types_and_universe_isolation(library):
    uid = library.create("universe", "Мир")["id"]
    other = library.create("universe", "Другой")["id"]
    target = library.create("article", "Герой", uid)
    alien = library.create("article", "Чужой", other)
    service = Templates(library.engine)
    template = service.create_with_fields(
        uid, "Спецслужба", [{"name": "Руководитель", "kind": "reference", "default": target["id"]}]
    )
    article = library.create("article", "Служба", uid)
    service.assign(uid, article["id"], template["id"])
    key = template["definitions"][0]["id"]
    with pytest.raises(ValueError):
        library.update("article", article["id"], {"fields": {key: alien["id"]}})
    with pytest.raises(ValueError):
        service.save(other, template["id"], "Чужой шаблон", [], 0)
    changed = [dict(template["definitions"][0], kind="bool")]
    with pytest.raises(ValueError):
        service.save(uid, template["id"], "Тип", changed, 0)
    Relations(library.engine).create(target["id"], article["id"], "работает в", "имеет сотрудника")
    assert Relations(library.engine).list_for(article["id"])[0]["article_id"] == target["id"]


def test_vertical_typed_editor_reference_navigation(qtbot, library):
    from arhitektor.ui.window import MainWindow

    uid = library.create("universe", "Мир")["id"]
    target = library.create("article", "Персонаж", uid)
    service = Templates(library.engine)
    template = service.create_with_fields(
        uid,
        "Спецслужба",
        [
            {"name": "Руководитель", "kind": "reference", "default": target["id"]},
            {"name": "Основана", "kind": "date", "default": "2020-01-01"},
            {
                "name": "Статус",
                "kind": "choice",
                "options": ["активна", "закрыта"],
                "default": "активна",
            },
            {"name": "Количество", "kind": "int", "default": 10},
        ],
    )
    article = library.create("article", "Служба", uid)
    service.assign(uid, article["id"], template["id"])
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.navigate(("article", article["id"]))
    qtbot.waitUntil(lambda: window.selected == ("article", article["id"]) and window.isEnabled())
    fields = window.fields["fields"]
    key = template["definitions"][-1]["id"]
    fields.typed[key].editor.setValue(42)
    fields.open_requested.emit(target["id"])
    qtbot.waitUntil(lambda: window.selected == ("article", target["id"]))
    assert library.get("article", article["id"])["fields"][key] == 42
    window.close()
    qtbot.waitUntil(lambda: window.closing)


def test_invalid_template_is_atomic_and_creation_uses_defaults(library):
    uid = library.create("universe", "Мир")["id"]
    service = Templates(library.engine)
    count = len(service.list(uid))
    with pytest.raises(ValueError):
        service.create_with_fields(
            uid, "Неверный", [{"name": "Дата", "kind": "date", "default": "вчера"}]
        )
    assert len(service.list(uid)) == count
    template = service.create_with_fields(
        uid, "Тест", [{"name": "Число", "kind": "int", "default": 5}]
    )
    article = service.create_article(uid, "Статья", template["id"])
    assert article["fields"][template["definitions"][0]["id"]] == 5
    count = len(library.catalog()["article"])
    with pytest.raises(ValueError):
        service.create_article(uid, "Ошибка", 999999)
    assert len(library.catalog()["article"]) == count
    service.save(uid, template["id"], "Тест", template["definitions"], 0)
    assert service.list(uid)[0]["id"] == template["id"]
    library.delete("universe", uid)
    assert not service.list(uid)


def test_template_dialog_edits_and_field_order(qtbot):
    from arhitektor.ui.templates import TemplateDialog

    definitions = [{"id": "stable", "name": "Численность", "kind": "int", "default": 12}]
    dialog = TemplateDialog({"title": "Спецслужба", "definitions": definitions}, [])
    qtbot.addWidget(dialog)
    dialog.definitions[0].name.setText("Количество сотрудников")
    dialog.add({"name": "История", "kind": "long"})
    dialog.move(dialog.definitions[1], -1)
    saved = [editor.read() for editor in dialog.definitions]
    assert saved[1]["id"] == "stable" and saved[1]["default"] == 12
    assert saved[1]["name"] == "Количество сотрудников"
    dialog.remove(dialog.definitions[0])
    assert len(dialog.definitions) == 1


def test_upgrade_0002_keeps_existing_relations(library):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    uid = library.create("universe", "Мир")["id"]
    a = library.create("article", "Лев", uid)
    b = library.create("article", "Служба", uid)
    identifier = Relations(library.engine).create(
        a["id"], b["id"], "работает в", "имеет сотрудника"
    )
    cfg = Config()
    cfg.set_main_option(
        "script_location",
        str(Path(__file__).parents[1] / "src/arhitektor/infrastructure/migrations"),
    )
    with library.engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, "0002")
    library.engine.dispose()
    upgraded = open_database(Path(library.engine.url.database))
    assert Relations(upgraded).list_for(a["id"])[0]["id"] == identifier
    assert Library(upgraded).get("article", b["id"])["template_id"] is not None
    upgraded.dispose()
