"""Compact relationship browsing and transactional selection removal."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QPushButton, QScrollArea, QWidget
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError

from arhitektor.infrastructure.database import open_database
from arhitektor.relations import Relations
from arhitektor.ui.relations import DeleteRelationsDialog, RelatedObjects, related_rows
from arhitektor.ui.window import MainWindow


def linked(library, count=10):
    universe = library.create("universe", "Мир")
    source = library.create("article", "Герой", universe["id"])
    targets, identifiers = [], []
    service = Relations(library.engine)
    for number in range(count):
        target = library.create("article", f"Цель {number}", universe["id"])
        target = library.update("article", target["id"], {"kind": "Организация"})
        targets.append(target)
        identifiers.append(service.create(source["id"], target["id"], "работает в", "нанимает"))
    return source, targets, identifiers


def open_article(qtbot, library, source):
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog) and window.isEnabled())
    window.navigate(("article", source["id"]))
    qtbot.waitUntil(lambda: window.selected == ("article", source["id"]) and window.isEnabled())
    return window


def close_window(qtbot, window):
    window.close()
    qtbot.waitUntil(lambda: window.closing)


@pytest.mark.parametrize("count", [1, 10, 1000])
def test_compact_model_rows_grow_without_nested_scroll(qtbot, count):
    catalog = {
        "article": [{"id": i, "title": f"Объект {i}", "kind": "Тип"} for i in range(count + 1)],
        "relation": [
            {
                "id": i,
                "source_id": 0,
                "target_id": i,
                "label": "прямое",
                "reverse_label": "обратное",
            }
            for i in range(1, count + 1)
        ],
    }
    panel = RelatedObjects(0, catalog)
    qtbot.addWidget(panel)
    panel.show()
    assert panel.proxy.rowCount() == count
    assert panel.results.height() >= count * 32
    assert not panel.findChildren(QScrollArea)
    assert panel.results.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert [b.text() for b in panel.findChildren(QPushButton)] == ["Добавить связь", "Убрать связь"]
    assert len(panel.findChildren(QWidget)) < 30  # No per-row widgets, including at 1000 rows.
    assert "Объект 1 · Тип · прямое" in panel.proxy.index(0, 0).data()
    panel.search.setText("ОБЪЕКТ 1")
    assert 0 < panel.proxy.rowCount() <= count
    panel.search.setText("ТИП")
    assert panel.proxy.rowCount() == count
    panel.search.setText("нет совпадений")
    assert panel.proxy.rowCount() == 0 and panel.empty.isVisible()
    assert "обратное" in related_rows(1, catalog)[0]["label"]


def test_row_click_saves_and_opens_target(qtbot, library):
    source, targets, _ = linked(library, 1)
    window = open_article(qtbot, library, source)
    panel = window.body.findChild(RelatedObjects)
    window.editor.setPlainText("Сохранить перед переходом")
    window.body_scroll.ensureWidgetVisible(panel)
    index = panel.proxy.index(0, 0)
    qtbot.mouseClick(
        panel.results.viewport(),
        Qt.MouseButton.LeftButton,
        pos=panel.results.visualRect(index).center(),
    )
    qtbot.waitUntil(lambda: window.selected == ("article", targets[0]["id"]) and window.isEnabled())
    assert library.get("article", source["id"])["content"] == "Сохранить перед переходом"
    qtbot.waitUntil(
        lambda: "нанимает" in window.body.findChild(RelatedObjects).proxy.index(0, 0).data()
    )
    assert not window.props.findChildren(RelatedObjects)
    close_window(qtbot, window)


def test_dialog_search_check_clear_cancel(qtbot, library):
    source, _, identifiers = linked(library)
    dialog = DeleteRelationsDialog(related_rows(source["id"], library.catalog()))
    qtbot.addWidget(dialog)
    assert dialog.proxy.rowCount() == 10 and not dialog.confirm.isEnabled()
    for i in range(3):
        dialog.model.setData(
            dialog.model.index(i), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
        )
    assert dialog.model.checked == set(identifiers[:3])
    assert dialog.count.text() == "Выбрано связей: 3"
    dialog.search.setText("ЦЕЛЬ 9")
    assert dialog.proxy.rowCount() == 1
    assert "работает в" in dialog.proxy.index(0, 0).data()
    assert len(dialog.model.checked) == 3  # Filtering never clears hidden selections.
    dialog.clear.click()
    assert not dialog.model.checked and not dialog.confirm.isEnabled()
    dialog.search.setText("ОРГАНИЗАЦИЯ")
    assert dialog.proxy.rowCount() == 10
    dialog.model.setData(
        dialog.model.index(0), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
    )
    dialog.reject()
    assert len(Relations(library.engine).list_for(source["id"])) == 10


def test_bulk_delete_preserves_articles_other_relations_and_restart(library):
    source, targets, identifiers = linked(library)
    service = Relations(library.engine)
    extra = service.create(targets[0]["id"], targets[1]["id"], "партнёр", "партнёр")
    commits = []

    def committed(_connection):
        commits.append(True)

    event.listen(library.engine, "commit", committed)
    try:
        service.delete_many(source["id"], identifiers[:3])
    finally:
        event.remove(library.engine, "commit", committed)
    assert len(commits) == 1
    assert {r["id"] for r in service.list_for(source["id"])} == set(identifiers[3:])
    assert service.list_for(targets[2]["id"]) == []
    assert [r["id"] for r in service.list_for(targets[0]["id"])] == [extra]
    assert len(library.catalog()["article"]) == 11
    path = library.engine.url.database
    library.engine.dispose()
    reopened = open_database(Path(path))
    try:
        assert len(Relations(reopened).list_for(source["id"])) == 7
        assert Relations(reopened).list_for(targets[2]["id"]) == []
    finally:
        reopened.dispose()


def fail_second_delete(library, identifier):
    with library.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TRIGGER fail_relation_delete BEFORE DELETE ON article_relations "
                f"WHEN OLD.id = {int(identifier)} BEGIN SELECT RAISE(ABORT, 'test failure'); END"
            )
        )


def test_bulk_delete_rolls_back_actual_database_failure(library):
    source, targets, identifiers = linked(library, 3)
    fail_second_delete(library, identifiers[1])
    with pytest.raises(IntegrityError):
        Relations(library.engine).delete_many(source["id"], identifiers)
    assert {r["id"] for r in Relations(library.engine).list_for(source["id"])} == set(identifiers)
    for target in targets:
        assert len(Relations(library.engine).list_for(target["id"])) == 1
    assert len(library.catalog()["article"]) == 4


def test_bulk_delete_validates_entire_selection(library):
    source, targets, identifiers = linked(library, 3)
    service = Relations(library.engine)
    unrelated = service.create(targets[0]["id"], targets[1]["id"], "другое", "другое")
    for invalid in (999999, unrelated):
        with pytest.raises(ValueError, match="Список связей изменился"):
            service.delete_many(source["id"], [identifiers[0], invalid])
    assert len(service.list_for(source["id"])) == 3


@pytest.mark.parametrize("fail", [False, True])
def test_window_bulk_dialog_commit_or_error(qtbot, library, fail):
    source, targets, identifiers = linked(library)
    if fail:
        fail_second_delete(library, identifiers[1])
    window = open_article(qtbot, library, source)
    errors = []

    def interact():
        try:
            dialog = window.findChild(DeleteRelationsDialog)
            assert dialog is not None and dialog.proxy.rowCount() == 10
            for i in range(3):
                dialog.model.setData(
                    dialog.model.index(i), Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole
                )
            dialog.confirm.click()
            if fail:
                qtbot.waitUntil(lambda: not dialog.error.isHidden())
                assert not dialog.busy and dialog.isVisible()
                assert len(dialog.model.checked) == 3
                assert window.body.findChild(RelatedObjects).proxy.rowCount() == 10
                assert len(window.catalog["relation"]) == 10
                dialog.reject()
            else:
                qtbot.waitUntil(lambda: not dialog.isVisible())
        except (AssertionError, qtbot.TimeoutError) as error:
            errors.append(error)
            dialog = window.findChild(DeleteRelationsDialog)
            if dialog:
                dialog.set_busy(False)
                dialog.reject()

    QTimer.singleShot(0, interact)
    window.body.findChild(RelatedObjects).remove.click()
    if errors:
        raise errors[0]
    remaining = 10 if fail else 7
    qtbot.waitUntil(lambda: window.body.findChild(RelatedObjects).proxy.rowCount() == remaining)
    assert len(Relations(library.engine).list_for(source["id"])) == remaining
    assert len(Relations(library.engine).list_for(targets[0]["id"])) == (1 if fail else 0)
    assert len(library.catalog()["article"]) == 11
    if not fail:
        window.navigate(("article", targets[0]["id"]))
        qtbot.waitUntil(
            lambda: window.selected == ("article", targets[0]["id"]) and window.isEnabled()
        )
        qtbot.waitUntil(lambda: window.body.findChild(RelatedObjects).proxy.rowCount() == 0)
    close_window(qtbot, window)


def test_card_scrolls_whole_list_at_small_height(qtbot, library):
    source, _, _ = linked(library)
    window = open_article(qtbot, library, source)
    window.resize(1000, 520)
    qtbot.waitUntil(lambda: window.body_scroll.verticalScrollBar().maximum() > 0)
    panel = window.body.findChild(RelatedObjects)
    assert panel.results.height() >= 320
    assert panel.results.verticalScrollBar().maximum() == 0
    assert window.body_scroll.horizontalScrollBar().maximum() == 0
    panel.search.setText("Цель 9")
    assert panel.proxy.rowCount() == 1
    assert panel.results.height() < 60
    close_window(qtbot, window)


def test_checkboxes_keyboard_and_busy_close(qtbot):
    rows = [{"id": 1, "article_id": 2, "title": "A [1]", "kind": "Тип", "label": "связь"}]
    dialog = DeleteRelationsDialog(rows)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.results.setCurrentIndex(dialog.proxy.index(0, 0))
    dialog.results.setFocus()
    qtbot.keyClick(dialog.results, Qt.Key.Key_Space)
    assert dialog.model.checked == {1}
    dialog.search.setText("[1]")
    assert dialog.proxy.rowCount() == 1  # Literal search, not a regular expression.
    with qtbot.waitSignal(dialog.delete_requested) as signal:
        dialog.confirm.click()
    assert signal.args == [[1]]
    dialog.set_busy(True)
    dialog.reject()
    dialog.close()
    assert dialog.isVisible()
    dialog.set_busy(False)
    dialog.reject()
    assert not dialog.isVisible()
