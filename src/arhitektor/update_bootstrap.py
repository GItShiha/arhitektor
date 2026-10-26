"""Stable standard-library-only Linux launch protocol (also copied outside releases)."""

import json
import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path


def data_dir():
    root = Path(os.environ.get("XDG_DATA_HOME", ""))
    return (root if root.is_absolute() else Path.home() / ".local/share") / "arhitektor"


def state_dir():
    return data_dir() / "updates"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def lease(path):
    import fcntl

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield stream


def schema(path):
    with sqlite3.connect(f"{Path(path).as_uri()}?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Проверка целостности библиотеки не пройдена")
        definitions = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchall()
        return json.dumps([definitions, revision], ensure_ascii=False)


def recover(folder):
    journal = read_json(folder / "transaction.json", {})
    if journal.get("phase") not in (None, "complete", "failed", "rolled_back", "blocked"):
        database = Path(journal["database"])
        if schema(database) != journal["schema"]:
            journal.update(
                phase="blocked", error="Схема изменилась. Автоматический возврат запрещён."
            )
        else:
            atomic(folder / "active.json", journal["previous"])
            journal.update(phase="failed", error="Обновление прервано; выбрана предыдущая версия.")
        atomic(folder / "transaction.json", journal)
    if journal.get("phase") == "blocked":
        raise RuntimeError(journal["error"])
    return journal


def execute(version):
    python = Path(version["python"])
    code = Path(version["code"])
    if not python.is_file() or not (code / "src/arhitektor/app.py").is_file():
        raise RuntimeError("Версия недоступна. Проверьте каталог updates/releases.")
    os.chdir(code)
    os.execv(str(python), [str(python), "-m", "arhitektor.app", *sys.argv[1:]])


def route():
    """Acquire a GUI lease before opening SQLite; every entry point uses this route."""
    if not sys.platform.startswith("linux"):
        return
    import fcntl

    global _gui_lease
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "install.lock").open("a") as installer:
        try:
            fcntl.flock(installer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            journal = read_json(folder / "transaction.json", {})
            if not (
                journal.get("phase") == "launching"
                and os.environ.get("ARHITEKTOR_TRIAL") == journal.get("token")
            ):
                raise RuntimeError("Установка ещё выполняется. Повторите запуск позже.")
        else:
            recover(folder)
        _gui_lease = (folder / "gui.lock").open("a")
        fcntl.flock(_gui_lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active = read_json(folder / "active.json")
        if active and (
            Path(active["code"]).resolve() != Path(__file__).resolve().parents[2]
            or Path(active["python"]).absolute() != Path(sys.executable).absolute()
        ):
            _gui_lease.close()
            execute(active)


def install_launcher(version, bin_dir=None, applications=None):
    """One-time explicit setup, never overwrite an existing user launcher."""
    folder = state_dir()
    folder.mkdir(parents=True, exist_ok=True)
    bin_dir = Path(bin_dir or Path.home() / ".local/bin")
    xdg = Path(os.environ.get("XDG_DATA_HOME", ""))
    applications = Path(
        applications
        or ((xdg if xdg.is_absolute() else Path.home() / ".local/share") / "applications")
    )
    launcher = bin_dir / "arhitektor-managed"
    desktop = applications / "arhitektor-managed.desktop"
    bootstrap = folder / "bootstrap.py"
    if any(p.exists() for p in (launcher, desktop, bootstrap)):
        raise RuntimeError("Запускатель уже существует. Существующие файлы не перезаписаны.")
    if any(c in str(launcher) + str(bootstrap) for c in "\n\r"):
        raise RuntimeError("Недопустимый путь запускателя")
    atomic(folder / "active.json", version)
    bootstrap.write_text(Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
    bin_dir.mkdir(parents=True, exist_ok=True)
    applications.mkdir(parents=True, exist_ok=True)
    # Python repr is code quoting; no shell or shell-specific activation is involved.
    with launcher.open("x", encoding="utf-8") as stream:
        stream.write(
            "#!/usr/bin/python3\nimport runpy\nrunpy.run_path("
            + repr(str(bootstrap))
            + ", run_name='__main__')\n"
        )
    launcher.chmod(0o755)
    argument = str(launcher).replace("%", "%%")
    for char in ("\\", '"', "`", "$"):
        argument = argument.replace(char, "\\" + char)
    argument = ('"' + argument + '"').replace("\\", "\\\\")
    with desktop.open("x", encoding="utf-8") as stream:
        stream.write(
            "[Desktop Entry]\nType=Application\nName=Архитектор\nExec="
            + argument
            + "\nTerminal=false\nCategories=Office;\n"
        )
    return launcher


if __name__ == "__main__":
    try:
        # Standalone bootstrap has no package dependencies.
        route()
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
