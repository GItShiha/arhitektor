from PySide6.QtWidgets import QMessageBox

from arhitektor.ui.window import MainWindow


def opened(qtbot, library):
    work = library.create("work", "Роман")
    scene = library.create("scene", "Начало", work["id"])
    second = library.create("scene", "Продолжение", work["id"])
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog))
    window.load(("scene", scene["id"]))
    qtbot.waitUntil(lambda: window.selected == ("scene", scene["id"]))
    return window, scene, second


def test_autosave_navigation_close_reopen(qtbot, library):
    window, first, second = opened(qtbot, library)
    window.editor.setPlainText("Русский текст сохраняется автоматически.")
    qtbot.waitUntil(lambda: not window.dirty, timeout=5000)
    assert library.get("scene", first["id"])["word_count"] == 4
    window.editor.setPlainText("Последнее изменение перед переходом")
    window.guard(lambda: window.load(("scene", second["id"])))
    qtbot.waitUntil(lambda: window.selected == ("scene", second["id"]))
    assert library.get("scene", first["id"])["content"] == "Последнее изменение перед переходом"
    window.editor.setPlainText("Сохранить при закрытии")
    window.close()
    qtbot.waitUntil(lambda: window.closing)
    assert library.get("scene", second["id"])["content"] == "Сохранить при закрытии"
    reopened = MainWindow(library)
    qtbot.addWidget(reopened)
    qtbot.waitUntil(lambda: bool(reopened.catalog))
    reopened.load(("scene", second["id"]))
    qtbot.waitUntil(lambda: reopened.selected == ("scene", second["id"]))
    assert reopened.editor.toPlainText() == "Сохранить при закрытии"
    reopened.close()
    qtbot.waitUntil(lambda: reopened.closing)


def test_failed_save_blocks_close(qtbot, library, monkeypatch):
    window, first, _ = opened(qtbot, library)
    original = library.update
    errors = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: errors.append(args[-1]))

    def fail(*args):
        raise OSError("Диск заполнен")

    monkeypatch.setattr(library, "update", fail)
    window.editor.setPlainText("Нельзя потерять")
    window.close()
    qtbot.waitUntil(lambda: bool(errors))
    assert window.dirty and window.isVisible() and not window.closing
    assert window.editor.toPlainText() == "Нельзя потерять"
    assert library.get("scene", first["id"])["content"] == ""
    monkeypatch.setattr(library, "update", original)
    window.close()
    qtbot.waitUntil(lambda: window.closing)
    assert library.get("scene", first["id"])["content"] == "Нельзя потерять"


def test_typing_during_save_is_not_marked_saved(qtbot, library, monkeypatch):
    from threading import Event

    window, first, _ = opened(qtbot, library)
    original = library.update
    entered, release = Event(), Event()

    def slow_update(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(library, "update", slow_update)
    window.editor.setPlainText("Первая версия")
    window.save()
    qtbot.waitUntil(entered.is_set)
    window.editor.setPlainText("Новая версия во время записи")
    release.set()
    qtbot.waitUntil(lambda: not window.saving)
    assert window.dirty
    qtbot.waitUntil(lambda: not window.dirty, timeout=5000)
    assert library.get("scene", first["id"])["content"] == "Новая версия во время записи"
    window.close()
    qtbot.waitUntil(lambda: window.closing)
