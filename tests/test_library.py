import json
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from arhitektor.infrastructure.database import data_directory, open_database
from arhitektor.services import Library, count_words


def test_migration_repeatable(library):
    engine = open_database(Path(library.engine.url.database))
    assert set(inspect(engine).get_table_names()) == {
        "universes",
        "articles",
        "works",
        "scenes",
        "alembic_version",
        "article_relations",
    }
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("select version_num from alembic_version").scalar() == "0002"
        )
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()


def test_full_workflow_and_reopen(library):
    universe = library.create("universe", "Мир")
    library.update("universe", universe["id"], {"settings": {"calendar": "Луны"}})
    article = library.create("article", "Герой", universe["id"])
    library.update(
        "article",
        article["id"],
        {"kind": "Свой тип", "content": "Путник с севера", "tags": ["ЛЁД"], "fields": {"age": 42}},
    )
    assert library.search(universe["id"], "лёд")[0]["id"] == article["id"]
    assert library.search(universe["id"], "ПУТНИК")[0]["id"] == article["id"]
    assert library.search(universe["id"], "%") == []
    work = library.create("work", "Роман", universe["id"])
    scene = library.create("scene", "Встреча", work["id"])
    library.update("scene", scene["id"], {"content": "Привет, мир! Кто-то здесь."})
    library.engine.dispose()
    reopened = open_database(Path(library.engine.url.database))
    row = Library(reopened).get("scene", scene["id"])
    assert row["content"] == "Привет, мир! Кто-то здесь."
    assert row["word_count"] == 4
    assert row["updated_at"] >= row["created_at"]
    reopened.dispose()


def test_standalone_and_delete_policy(library):
    universe = library.create("universe", "Мир")
    article = library.create("article", "Статья", universe["id"])
    work = library.create("work", "Роман", universe["id"])
    scene = library.create("scene", "Начало", work["id"])
    standalone = library.create("work", "Рассказ")
    assert standalone["universe_id"] is None
    library.delete("universe", universe["id"])
    assert library.get("work", work["id"])["universe_id"] is None
    with pytest.raises(ValueError):
        library.get("article", article["id"])
    assert library.get("scene", scene["id"])
    library.delete("work", work["id"])
    with pytest.raises(ValueError):
        library.get("scene", scene["id"])


def test_order_delete_append(library):
    work = library.create("work", "Роман")
    scenes = [library.create("scene", str(i), work["id"]) for i in range(3)]
    library.move_scene(scenes[2]["id"], -1)
    rows = library.catalog()["scene"]
    assert [r["id"] for r in rows] == [scenes[0]["id"], scenes[2]["id"], scenes[1]["id"]]
    library.delete("scene", scenes[2]["id"])
    library.create("scene", "Конец", work["id"])
    assert [r["position"] for r in library.catalog()["scene"]] == [0, 1, 2]
    library.move_scene(scenes[0]["id"], -1)
    assert library.get("scene", scenes[0]["id"])["position"] == 0


def test_failed_transaction_keeps_data(library):
    work = library.create("work", "Целое")
    with pytest.raises(IntegrityError):
        library.update("work", work["id"], {"title": "Не сохранится", "universe_id": 999})
    assert library.get("work", work["id"])["title"] == "Целое"
    with pytest.raises(ValueError):
        library.create("article", "Без мира")
    with pytest.raises(ValueError):
        library.update("work", work["id"], {"title": " "})
    with pytest.raises(ValueError):
        library.update("work", work["id"], {"id": 8})


def test_backup_export(library, tmp_path):
    work = library.create("work", "Живая история")
    scene = library.create("scene", "Начало", work["id"])
    library.update("scene", scene["id"], {"content": "Текст из WAL"})
    backup = library.backup(tmp_path / "backup.sqlite3")
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("select content from scenes").fetchone() == ("Текст из WAL",)
    restored = open_database(backup)
    assert Library(restored).get("work", work["id"])["title"] == "Живая история"
    restored.dispose()
    exported = library.export(tmp_path / "export.json")
    payload = json.loads(exported.read_text())
    assert payload["version"] == 1
    assert payload["data"]["scene"][0]["content"] == "Текст из WAL"
    with pytest.raises(ValueError):
        library.backup(backup)
    with pytest.raises(ValueError):
        library.export(exported)


def test_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert data_directory() == tmp_path / "arhitektor"
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    assert data_directory().is_absolute()


@pytest.mark.parametrize("text, expected", [("", 0), ("Привет, мир!", 2), ("кто-то 你好 123", 3)])
def test_word_count(text, expected):
    assert count_words(text) == expected
