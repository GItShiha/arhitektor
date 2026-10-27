"""Update protocol: actual Git, SQLite/WAL, leases, subprocesses and Qt."""

import shutil
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from arhitektor import updater as u
from arhitektor.update_bootstrap import atomic, install_launcher, lease, read_json, recover, schema


def git(root, *args):
    return u.git(root, *args)


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "remote", "add", "origin", next(iter(u.EXPECTED)))
    (root / "file").write_text("old")
    git(root, "add", ".")
    git(root, "commit", "-m", "old")
    old = git(root, "rev-parse", "HEAD")
    (root / "file").write_text("new")
    git(root, "commit", "-am", "new")
    target = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/origin/main", target)
    git(root, "checkout", "--detach", old)
    return root, old, target


def test_revision_graph_and_source(repository):
    root, old, target = repository
    assert u.check(root, fetch=False)["target"] == target
    assert u.check(root, fetch=False)["current"] == old
    git(root, "checkout", "--detach", target)
    assert not u.check(root, fetch=False)["available"]
    git(root, "checkout", "--detach", old)
    (root / "local").write_text("preserve")
    with pytest.raises(u.UpdateError, match="локальные"):
        u.check(root, fetch=False)
    assert (root / "local").read_text() == "preserve"
    (root / "local").unlink()
    (root / "file").write_text("fork")
    git(root, "commit", "-am", "fork")
    with pytest.raises(u.UpdateError, match="разошлись"):
        u.check(root, fetch=False)
    git(root, "remote", "set-url", "origin", "https://example.invalid/repo")
    with pytest.raises(u.UpdateError, match="origin"):
        u.check(root, fetch=False)


@pytest.mark.parametrize("origin", sorted(u.EXPECTED))
def test_official_origins(repository, origin):
    root, old, _ = repository
    git(root, "remote", "set-url", "origin", origin)
    assert u.validate(root) == old


def test_subprocess_error_hides_secrets():
    with pytest.raises(u.UpdateError) as error:
        u.run([sys.executable, "-c", "import sys; print('SECRET',file=sys.stderr); sys.exit(1)"])
    assert "SECRET" not in str(error.value)
    with pytest.raises(u.UpdateError, match="время"):
        u.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.02)


def test_wal_backup_schema_and_restart(library, tmp_path):
    world = library.create("universe", "Мир")
    article = library.create("article", "Текст", world["id"])
    library.update("article", article["id"], {"content": "Новая глава"})
    source = Path(library.engine.url.database)
    copy = tmp_path / "safe.sqlite3"
    u.backup_database(source, copy)
    assert schema(copy) == schema(source)
    assert len(library.catalog()["template"]) > 0
    with pytest.raises(ValueError):
        u.backup_database(source, copy)
    bad = tmp_path / "bad.sqlite3"
    bad.write_bytes(b"corrupt")
    with pytest.raises(Exception, match="database"):
        schema(bad)


@pytest.mark.parametrize("phase", ["preparing", "testing", "backing_up", "launching"])
def test_power_failure_never_restores_data(library, tmp_path, phase):
    database = Path(library.engine.url.database)
    previous = {"revision": "old"}
    folder = tmp_path / "updates"
    atomic(folder / "active.json", {"revision": "broken"})
    atomic(
        folder / "transaction.json",
        {
            "phase": phase,
            "previous": previous,
            "database": str(database),
            "schema": schema(database),
        },
    )
    library.create("universe", "Новый текст после обновления")
    assert recover(folder)["phase"] == "failed"
    assert read_json(folder / "active.json") == previous
    assert library.catalog()["universe"][0]["title"] == "Новый текст после обновления"
    assert recover(folder)["phase"] == "failed"


def test_recovery_blocks_unknown_schema(library, tmp_path):
    database = Path(library.engine.url.database)
    folder = tmp_path / "updates"
    atomic(
        folder / "transaction.json",
        {"phase": "launching", "previous": {}, "database": str(database), "schema": "unknown"},
    )
    with pytest.raises(RuntimeError, match="Схема"):
        recover(folder)
    assert read_json(folder / "transaction.json")["phase"] == "blocked"


def test_exclusive_lease_in_real_process(tmp_path):
    path = tmp_path / "lock"
    with lease(path), pytest.raises(u.UpdateError):
        u.run(
            [
                sys.executable,
                "-c",
                (
                    "from arhitektor.update_bootstrap import lease; "
                    f"ctx=lease({str(path)!r}); ctx.__enter__()"
                ),
            ]
        )
    with lease(path):
        pass


def test_launcher_no_overwrite_and_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "custom"))
    v = {"code": str(u.ROOT), "python": sys.executable, "revision": "fixture"}
    launcher = install_launcher(v, tmp_path / "bin", tmp_path / "apps")
    assert launcher.stat().st_mode & 0o111
    assert (tmp_path / "apps/arhitektor-managed.desktop").is_file()
    with pytest.raises(RuntimeError, match="существует"):
        install_launcher(v, tmp_path / "bin", tmp_path / "apps")
    assert read_json(tmp_path / "custom/arhitektor/updates/active.json") == v


def test_real_library_window_probe(library, tmp_path):
    copy = tmp_path / "probe.sqlite3"
    u.backup_database(Path(library.engine.url.database), copy)
    u.probe(u.version(), copy, tmp_path / "xdg")


@pytest.mark.parametrize("failure", ["prepare", "backup", "probe", "pytest", None])
def test_transaction_failures_preserve_checkout_and_data(
    repository, library, tmp_path, monkeypatch, failure
):
    root, old, target = repository
    database = Path(library.engine.url.database)
    library.create("universe", "Неприкосновенный текст")
    before = database.read_bytes()
    folder = tmp_path / "updates"
    candidate = {"code": str(root), "python": sys.executable, "revision": target}
    monkeypatch.setattr(u, "preflight", lambda *a: None)
    monkeypatch.setattr(u, "check", lambda *a: {"target": target})

    def prepare(*args):
        if failure == "prepare":
            raise u.UpdateError("Подготовка не удалась")
        return candidate

    monkeypatch.setattr(u, "prepare", prepare)
    real_backup = u.backup_database

    def backup(*args):
        if failure == "backup":
            raise u.UpdateError("Копия не создана")
        return real_backup(*args)

    monkeypatch.setattr(u, "backup_database", backup)

    def probe(*args):
        if failure == "probe":
            raise u.UpdateError("Ошибка миграции или чтения копии")

    monkeypatch.setattr(u, "probe", probe)
    real_run = u.run

    def run(args, **kw):
        if "pytest" in args:
            if failure == "pytest":
                raise u.UpdateError("Тесты новой версии не пройдены")
            return ""
        return real_run(args, **kw)

    monkeypatch.setattr(u, "run", run)
    monkeypatch.setattr(u, "launch", lambda *a: None)
    if failure:
        with pytest.raises(u.UpdateError):
            u.install(root, target, database, folder)
        assert read_json(folder / "active.json")["revision"] == old
    else:
        assert u.install(root, target, database, folder)
        assert read_json(folder / "active.json")["revision"] == target
    assert git(root, "rev-parse", "HEAD") == old
    assert (root / "file").read_text() == "old"
    assert database.read_bytes() == before
    assert library.catalog()["universe"][0]["title"] == "Неприкосновенный текст"


def test_deferred_notifications_and_manual_check(qtbot, library, monkeypatch, tmp_path):
    from arhitektor.ui.window import MainWindow

    monkeypatch.setenv("ARHITEKTOR_PROBE", "1")
    window = MainWindow(library)
    qtbot.addWidget(window)
    panel = window.updates
    panel.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    first = {"current": "a" * 40, "target": "b" * 40, "available": True, "checked_at": "today"}
    panel.checked(first)
    panel.later()
    panel.checked(first)
    assert panel.notice.isHidden()
    panel.checked(first, manual=True)
    assert not panel.notice.isHidden()
    panel.later()
    panel.checked({**first, "target": "c" * 40})
    assert not panel.notice.isHidden()
    panel.shutdown()
    qtbot.waitUntil(lambda: window.isEnabled())
    window.close()
    qtbot.waitUntil(lambda: window.closing)


@pytest.mark.parametrize("changed", [False, True])
def test_preflight_disk_and_target(repository, library, tmp_path, monkeypatch, changed):
    root, _, target = repository
    monkeypatch.setattr(
        u, "check", lambda *a: {"target": "changed" if changed else target, "available": True}
    )
    monkeypatch.setattr(u.shutil, "disk_usage", lambda *a: type("Usage", (), {"free": 0})())
    with pytest.raises(u.UpdateError, match="main|места"):
        u.preflight(root, target, Path(library.engine.url.database), tmp_path)


def test_legacy_qlock_blocks_installer(library):
    from PySide6.QtCore import QLockFile

    database = Path(library.engine.url.database)
    lock = QLockFile(str(database.parent / "application.lock"))
    assert lock.tryLock(0)
    try:
        with pytest.raises(u.UpdateError, match="открыта"), u.application_lock(database):
            pass
    finally:
        lock.unlock()


@pytest.mark.parametrize("step", ["worktree", "venv", "install", "check"])
def test_prepare_failure_never_changes_original(repository, tmp_path, monkeypatch, step):
    root, old, target = repository
    git(root, "checkout", "--detach", target)
    (root / "src/arhitektor").mkdir(parents=True)
    (root / "src/arhitektor/update_probe.py").write_text("# protocol")
    git(root, "add", ".")
    git(root, "commit", "-m", "protocol")
    target = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "--detach", old)
    real = u.run

    def commands(args, **kwargs):
        if step in [str(a) for a in args]:
            raise u.UpdateError("injected " + step)
        if str(args[0]) == "git":
            return real(args, **kwargs)
        return ""

    monkeypatch.setattr(u, "run", commands)
    monkeypatch.setattr(u.shutil, "which", lambda _: None)
    with pytest.raises(u.UpdateError, match="injected"):
        u.prepare(root, target, tmp_path / "updates")
    assert git(root, "rev-parse", "HEAD") == old
    assert not (root / ".venv").exists()


def test_real_release_activation_restart_and_rollback(library, tmp_path, monkeypatch):
    """Offline integration: dependencies reused, code/venv/worktrees/processes are real."""
    root = tmp_path / "source"
    shutil.copytree(
        u.ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
    )
    (root / ".gitignore").write_text("__pycache__/\n")
    (root / "tests").mkdir()
    (root / "tests/test_release.py").write_text(
        "def test_release_import():\n import arhitektor\n from pathlib import Path\n"
        " assert Path.cwd() in Path(arhitektor.__file__).parents\n"
    )
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "remote", "add", "origin", next(iter(u.EXPECTED)))
    git(root, "add", ".")
    git(root, "commit", "-m", "old")
    old = git(root, "rev-parse", "HEAD")
    (root / "release-marker").write_text("second version")
    git(root, "add", ".")
    git(root, "commit", "-m", "next")
    target = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/origin/main", target)
    git(root, "checkout", "--detach", old)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "live"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from arhitektor.infrastructure.database import open_database
    from arhitektor.services import Library

    database = tmp_path / "live/arhitektor/library.sqlite3"
    live = Library(open_database(database))
    world = live.create("universe", "Мой мир")
    live.create("article", "Текст до обновления", world["id"])
    folder = database.parent / "updates"
    real_check = u.check
    monkeypatch.setattr(u, "check", lambda r: real_check(r, fetch=False))

    # Reuse already installed test dependencies without contacting PyPI. The new interpreter
    # imports the detached release's source before the shared dependency directory.
    def prepare(r, sha, f):
        code = f / "releases" / sha / "code"
        code.parent.mkdir(parents=True)
        git(r, "worktree", "add", "--detach", code, sha)
        venv = code.parent / "venv"
        u.run([sys.executable, "-m", "venv", "--without-pip", venv])
        site = next((venv / "lib").glob("python*/site-packages"))
        dependency_site = Path(pytest.__file__).resolve().parent.parent
        (site / "release.pth").write_text(
            f"import sys; sys.path.insert(0, {str(code / 'src')!r}); sys.path.append({str(dependency_site)!r})\n"
        )
        return {"code": str(code), "python": str(venv / "bin/python"), "revision": sha}

    monkeypatch.setattr(u, "prepare", prepare)
    # Use the source checkout's code for previous-version probes too.
    previous = prepare(root, old, folder)
    atomic(folder / "active.json", previous)
    real_version = u.version
    monkeypatch.setattr(u, "version", lambda r: previous if Path(r) == root else real_version(r))
    processes = []
    real_launch = u.launch

    def launch(*args):
        p = real_launch(*args)
        processes.append(p)
        return p

    monkeypatch.setattr(u, "launch", launch)
    try:
        assert u.install(root, target, database, folder)
        active = read_json(folder / "active.json")
        assert active["revision"] == target
        assert processes[-1].poll() is None
        with pytest.raises(u.UpdateError):
            u.run([active["python"], "-m", "arhitektor.app"], cwd=active["code"], timeout=5)
        processes[-1].terminate()
        processes[-1].wait(timeout=10)
        # New data is retained by manual rollback; rollback performs new copy/read checks.
        live.create("article", "Текст после обновления", world["id"])
        monkeypatch.setattr(u, "version", lambda _: active)
        assert u.install(Path(active["code"]), "rollback", database, folder, rollback=True)
        assert read_json(folder / "active.json")["revision"] == old
        assert len(live.catalog()["article"]) == 2
        assert git(root, "rev-parse", "HEAD") == old
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
            p.wait(timeout=10)
        live.engine.dispose()


def test_failed_launch_rolls_back_code_without_replacing_new_data(
    repository, library, tmp_path, monkeypatch
):
    root, old, target = repository
    database = Path(library.engine.url.database)
    folder = tmp_path / "updates"
    monkeypatch.setattr(u, "preflight", lambda *a: None)
    monkeypatch.setattr(u, "check", lambda *a: {"target": target})
    monkeypatch.setattr(
        u, "prepare", lambda *a: {"code": str(root), "python": sys.executable, "revision": target}
    )
    monkeypatch.setattr(u, "probe", lambda *a: None)
    real_run = u.run
    monkeypatch.setattr(
        u, "run", lambda args, **kw: "" if "pytest" in args else real_run(args, **kw)
    )
    launches = []

    def launch(ver, folder, token=None):
        launches.append(ver["revision"])
        if token:
            library.create("universe", "Новые данные не заменять")
            raise u.UpdateError("Неудачный старт")

    monkeypatch.setattr(u, "launch", launch)
    assert not u.install(root, target, database, folder)
    assert launches == [target, old]
    assert library.catalog()["universe"][0]["title"] == "Новые данные не заменять"
    assert read_json(folder / "active.json")["revision"] == old


def test_check_process_leaves_qt_event_loop_responsive(qtbot, library, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer

    from arhitektor.ui.window import MainWindow

    monkeypatch.setenv("ARHITEKTOR_PROBE", "1")
    window = MainWindow(library)
    qtbot.addWidget(window)
    panel = window.updates
    panel.settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    panel.enabled = True
    ticks = []
    timer = QTimer(window)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(5)
    panel.check(True)
    qtbot.waitUntil(lambda: panel.process is None, timeout=10000)
    assert ticks
    panel.shutdown()
    qtbot.waitUntil(lambda: window.isEnabled())
    window.close()
    qtbot.waitUntil(lambda: window.closing)


def test_confirmation_pins_revision_and_cancel_is_noop(qtbot, library, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from arhitektor.ui.window import MainWindow

    monkeypatch.setenv("ARHITEKTOR_PROBE", "1")
    window = MainWindow(library)
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.isEnabled())
    panel = window.updates
    panel.target = "a" * 40
    commands = []
    installed = []
    monkeypatch.setattr(
        panel,
        "command",
        lambda action, callback, extra=(): (commands.append((action, extra)), callback({})),
    )
    monkeypatch.setattr(window, "guard", lambda callback: callback())
    monkeypatch.setattr(
        panel, "close_for_install", lambda rollback, target: installed.append(target)
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    panel.confirm()
    assert not commands and not installed

    def answer(*args):
        assert "a" * 40 in args[2]
        panel.target = "b" * 40  # New automatic result while the modal is open.
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", answer)
    panel.confirm()
    assert installed == ["a" * 40]
    assert commands[0][1][1] == "a" * 40
    panel.shutdown()
    window.close()
    qtbot.waitUntil(lambda: window.closing)


def test_save_failure_cannot_start_installer(qtbot, library, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from arhitektor.ui.window import MainWindow

    monkeypatch.setenv("ARHITEKTOR_PROBE", "1")
    work = library.create("work", "Роман")
    scene = library.create("scene", "Глава", work["id"])
    window = MainWindow(library)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: bool(window.catalog) and window.isEnabled())
    window.navigate(("scene", scene["id"]))
    qtbot.waitUntil(lambda: window.selected == ("scene", scene["id"]) and window.isEnabled())
    errors = []
    monkeypatch.setattr(window, "error", errors.append)

    def failed(*args):
        raise OSError("Нет доступа для записи")

    monkeypatch.setattr(library, "update", failed)
    window.editor.setPlainText("Несохранённая глава")
    panel = window.updates
    panel.target = "a" * 40
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(panel, "command", lambda action, callback, extra=(): callback({}))
    panel.confirm()
    qtbot.waitUntil(lambda: bool(errors) and not window.saving)
    assert window.dirty and not window.closing and panel.installer is None
    assert not getattr(window, "close_action", None)
    assert window.editor.toPlainText() == "Несохранённая глава"
    window.timer.stop()
    window.dirty = False  # Test teardown only; the actual editor remains open after failure.
    window.close()
    qtbot.waitUntil(lambda: window.closing)
