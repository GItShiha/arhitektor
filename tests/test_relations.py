import json
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

from arhitektor.infrastructure.database import open_database
from arhitektor.relations import Relations
from arhitektor.services import Library
from arhitektor.ui.relations import RelatedObjects, RelationDialog
from arhitektor.ui.window import MainWindow


def pair(library):
    universe = library.create("universe", "Мир")
    return [library.create("article", name, universe["id"]) for name in ("Лев", "Служба")]


def test_bidirectional_duplicate_delete_and_restart(library, tmp_path):
    person, org = pair(library)
    relations = Relations(library.engine)
    identifier = relations.create(person["id"], org["id"], "работает в", "имеет сотрудника")
    assert relations.list_for(org["id"])[0]["label"] == "имеет сотрудника"
    assert relations.list_for(person["id"])[0]["article_id"] == org["id"]
    with pytest.raises(ValueError, match="уже существует"):
        relations.create(person["id"], org["id"], "РАБОТАЕТ В", "сотрудник")
    with pytest.raises(ValueError, match="уже существует"):
        relations.create(org["id"], person["id"], "имеет сотрудника", "работает в")
    exported = library.export(tmp_path / "export.json")
    assert len(json.loads(exported.read_text())["data"]["relation"]) == 1
    backup = library.backup(tmp_path / "copy.sqlite3")
    restored = open_database(backup)
    assert Relations(restored).list_for(org["id"])[0]["article_id"] == person["id"]
    restored.dispose()
    relations.delete(identifier)
    assert not relations.list_for(person["id"])
    relations.create(person["id"], org["id"], "работает в", "имеет сотрудника")
    library.delete("article", person["id"])
    assert not relations.list_for(org["id"])
    assert library.get("article", org["id"])["title"] == "Служба"


def test_invalid_relationships(library):
    person, org = pair(library)
    other = library.create("universe", "Другой")
    alien = library.create("article", "Чужой", other["id"])
    relations = Relations(library.engine)
    for target, label in (
        (alien["id"], "связь"),
        (person["id"], "связь"),
        (99999, "связь"),
        (org["id"], " "),
    ):
        with pytest.raises(ValueError):
            relations.create(person["id"], target, label, "обратно")
    assert not relations.list_for(person["id"])


def test_migration_keeps_legacy_fields_and_makes_backup(tmp_path):
    path = tmp_path / "old.sqlite3"
    engine = create_engine("sqlite:///" + str(path))
    cfg = Config()
    cfg.set_main_option(
        "script_location",
        str(Path(__file__).parents[1] / "src/arhitektor/infrastructure/migrations"),
    )
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "0001")
    person, org = pair(Library(engine))
    values = {"имя": "Лев", "семья": [None, {"сестра": "Анна"}]}
    Library(engine).update("article", person["id"], {"fields": values, "kind": "Свой старый тип"})
    engine.dispose()
    upgraded = open_database(path)
    row = Library(upgraded).get("article", person["id"])
    assert row["fields"] == values and row["kind"] == "Свой старый тип"
    copies = list((tmp_path / "backups").glob("*.sqlite3"))
    assert len(copies) == 1
    with sqlite3.connect(copies[0]) as connection:
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == "0001"
        assert connection.execute("select count(*) from articles").fetchone()[0] == 2
    Relations(upgraded).create(person["id"], org["id"], "знает", "знает")
    upgraded.dispose()
    reopened = open_database(path)
    assert len(Relations(reopened).list_for(person["id"])) == 1
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    reopened.dispose()


def test_relation_ui_filters_and_guarded_navigation(qtbot, library):
    person, org = pair(library)
    library.update("article", org["id"], {"kind": "Организация"})
    dialog = RelationDialog([person, library.get("article", org["id"])])
    qtbot.addWidget(dialog)
    dialog.kind.setCurrentIndex(dialog.kind.findData("Организация"))
    dialog.search.setText("СЛУЖ")
    assert dialog.results.count() == 1
    dialog.results.setCurrentRow(0)
    assert dialog.values()[0] == org["id"] and dialog.confirm.isEnabled()
    Relations(library.engine).create(person["id"], org["id"], "работает в", "имеет сотрудника")
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.navigate(("article", org["id"]))
    qtbot.waitUntil(lambda: window.selected == ("article", org["id"]))
    window.editor.setPlainText("Сохрани перед переходом")
    panel = window.body.findChild(RelatedObjects)
    panel.open_requested.emit(person["id"])
    qtbot.waitUntil(lambda: window.selected == ("article", person["id"]))
    assert library.get("article", org["id"])["content"] == "Сохрани перед переходом"
    window.close()
    qtbot.waitUntil(lambda: window.closing)
