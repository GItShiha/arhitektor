"""Linux installer. Trusted Git source, isolated releases, conservative schema policy."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from arhitektor.update_bootstrap import atomic, lease, read_json, recover, schema, state_dir

EXPECTED = {
    "https://github.com/GItShiha/arhitektor",
    "https://github.com/GItShiha/arhitektor.git",
    "git@github.com:GItShiha/arhitektor",
    "git@github.com:GItShiha/arhitektor.git",
    "ssh://git@github.com/GItShiha/arhitektor",
    "ssh://git@github.com/GItShiha/arhitektor.git",
}
ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = 1


class UpdateError(RuntimeError):
    pass


def run(args, cwd=None, timeout=120, env=None):
    try:
        result = subprocess.run(
            [str(a) for a in args],
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise UpdateError(
            "Команда недоступна или превышено время ожидания: " + Path(str(args[0])).name
        ) from error
    if result.returncode:
        raise UpdateError(
            "Ошибка "
            + Path(str(args[0])).name
            + ". Проверьте сеть, права и зависимости. Вывод скрыт для защиты секретов."
        )
    return result.stdout.strip()


def git(root, *args):
    return run(["git", "-C", root, *args])


def validate(root):
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != Path(root).resolve():
        raise UpdateError("Нужен корневой каталог Git приложения")
    if git(root, "config", "--get-all", "remote.origin.url") not in EXPECTED:
        raise UpdateError("Источник origin не соответствует официальному репозиторию")
    # get-url also accounts for URL rewriting via insteadOf.
    if git(root, "remote", "get-url", "origin") not in EXPECTED:
        raise UpdateError("Подмена адреса origin; обновление заблокировано")
    if git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise UpdateError("Есть локальные изменения. Сохраните их; checkout не будет перезаписан.")
    return git(root, "rev-parse", "HEAD")


def check(root=ROOT, fetch=True):
    if not sys.platform.startswith("linux"):
        raise UpdateError("Обновление поддерживается только в Linux")
    current = validate(root)
    if fetch:
        git(root, "fetch", "--no-tags", "origin", "refs/heads/main:refs/remotes/origin/main")
    target = git(root, "rev-parse", "refs/remotes/origin/main")
    if not re.fullmatch(r"[0-9a-f]{40,64}", target):
        raise UpdateError("Некорректная ревизия main")
    if current != target:
        try:
            git(root, "merge-base", "--is-ancestor", current, target)
        except UpdateError as error:
            raise UpdateError("Истории разошлись или локальная ветка опережает main") from error
    return {
        "current": current,
        "target": target,
        "available": current != target,
        "checked_at": datetime.now(UTC).isoformat(),
    }


def version(root=ROOT, python=None):
    return {
        "code": str(Path(root).resolve()),
        "python": python or sys.executable,
        "revision": git(root, "rev-parse", "HEAD"),
    }


def log(folder, message):
    with (folder / "events.log").open("a", encoding="utf-8") as stream:
        stream.write(datetime.now(UTC).isoformat() + " " + message + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def migration_digest(root):
    folder = Path(root) / "src/arhitektor/infrastructure/migrations"
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    }


def environment():
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "ARHITEKTOR_TRIAL", "ARHITEKTOR_READY"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def preflight(root, target, database, folder):
    result = check(root)
    if result["target"] != target or not result["available"]:
        raise UpdateError("main изменилась. Проверьте обновления и подтвердите новую ревизию.")
    folder.mkdir(parents=True, exist_ok=True)
    required = max(2 * 1024**3, Path(database).stat().st_size * 4)
    if shutil.disk_usage(folder).free < required:
        raise UpdateError("Недостаточно места: нужно не менее 2 ГиБ и места для копий базы")
    return result


def prepare(root, target, folder):
    release = folder / "releases" / (target + "-" + uuid.uuid4().hex[:8])
    release.mkdir(parents=True)
    code = release / "code"
    git(root, "worktree", "add", "--detach", code, target)
    if not (code / "src/arhitektor/update_probe.py").is_file():
        raise UpdateError("Версия не поддерживает протокол безопасного обновления")
    if migration_digest(root) != migration_digest(code):
        raise UpdateError("Изменены миграции. Эта версия обновлятора блокирует изменение схемы.")
    python = release / "venv/bin/python"
    env = environment()
    if shutil.which("uv") and (code / "uv.lock").is_file():
        env["UV_PROJECT_ENVIRONMENT"] = str(release / "venv")
        run(
            ["uv", "sync", "--frozen", "--extra", "dev", "--python", sys.executable],
            cwd=code,
            timeout=900,
            env=env,
        )
        run(["uv", "pip", "check", "--python", python], env=env)
    else:
        run([sys.executable, "-m", "venv", release / "venv"], env=env)
        run([python, "-m", "pip", "install", "-e", str(code) + "[dev]"], timeout=900, env=env)
    # uv environments do not necessarily contain pip. Seed it only into the new venv.
    run([python, "-m", "ensurepip"], env=env)
    run([python, "-m", "pip", "check"], env=env)
    run(
        [
            python,
            "-c",
            (
                "import sys,PySide6,sqlalchemy,alembic; assert sys.version_info >= (3,12); "
                "import arhitektor.app,arhitektor.services"
            ),
        ],
        env=env,
    )
    return {"code": str(code), "python": str(python), "revision": target}


def probe(ver, database, temporary):
    env = environment()
    env.update(
        QT_QPA_PLATFORM="offscreen",
        XDG_DATA_HOME=str(temporary),
        XDG_CONFIG_HOME=str(temporary / "config"),
    )
    run(
        [ver["python"], "-m", "arhitektor.update_probe", database],
        cwd=ver["code"],
        env=env,
        timeout=90,
    )


def launch(ver, folder, token=None):
    env = environment()
    ready = folder / ("ready-" + uuid.uuid4().hex + ".json")
    if token:
        env.update(ARHITEKTOR_TRIAL=token, ARHITEKTOR_READY=str(ready))
    process = subprocess.Popen(
        [ver["python"], "-m", "arhitektor.app"],
        cwd=ver["code"],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    if not token:
        return process
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline and process.poll() is None:
        if read_json(ready, {}).get("token") == token:
            time.sleep(2)
            if process.poll() is None:
                ready.unlink(missing_ok=True)
                return process
            break
        time.sleep(0.1)
    # This is the unready trial process, never the user's original GUI.
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    raise UpdateError("Новая версия не подтвердила открытие библиотеки и запуск окна")


def backup_database(database, destination):
    from sqlalchemy import create_engine

    from arhitektor.services import Library

    engine = create_engine("sqlite:///" + str(database))
    try:
        Library(engine).backup(destination)
    finally:
        engine.dispose()
    schema(destination)


@contextmanager
def application_lock(database):
    from PySide6.QtCore import QLockFile

    lock = QLockFile(str(Path(database).parent / "application.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        raise UpdateError("Библиотека ещё открыта другим экземпляром приложения")
    try:
        yield
    finally:
        lock.unlock()


def safe_previous(journal, database):
    if not journal.get("previous") or schema(database) != journal.get("schema"):
        raise UpdateError("Схема несовместима; автоматический возврат кода запрещён")
    previous = journal["previous"]
    if validate(previous["code"]) != previous["revision"]:
        raise UpdateError("Предыдущая версия изменена; возврат заблокирован")
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "library.sqlite3"
        backup_database(database, copy)
        probe(previous, copy, Path(scratch))
    return previous


def install(root, target, database, folder=None, rollback=False):
    folder = Path(folder or state_dir())
    folder.mkdir(parents=True, exist_ok=True)
    with lease(folder / "install.lock"):
        recover(folder)
        # GUI holds the same lease until its process actually exits.
        with lease(folder / "gui.lock"), application_lock(database):
            previous = version(root)
            original_schema = schema(database)
            journal = {
                "phase": "preparing",
                "previous": previous,
                "database": str(database),
                "schema": original_schema,
                "target": target,
                "token": uuid.uuid4().hex,
            }
            old_journal = read_json(folder / "transaction.json", {})
            atomic(folder / "transaction.json", journal)
            try:
                if rollback:
                    candidate = safe_previous(old_journal, database)
                else:
                    preflight(root, target, database, folder)
                    candidate = None
                if candidate is None:
                    candidate = prepare(root, target, folder)
                journal["phase"] = "backing_up"
                atomic(folder / "transaction.json", journal)
                backup = folder.parent / "backups" / ("pre-update-" + uuid.uuid4().hex + ".sqlite3")
                backup_database(database, backup)
                journal.update(phase="testing", backup=str(backup))
                atomic(folder / "transaction.json", journal)
                with tempfile.TemporaryDirectory(dir=folder) as scratch:
                    scratch = Path(scratch)
                    test_db = scratch / "library.sqlite3"
                    backup_database(backup, test_db)
                    probe(candidate, test_db, scratch)
                    if schema(test_db) != original_schema:
                        raise UpdateError("Новая версия меняет схему. Установка заблокирована.")
                    probe(previous, test_db, scratch)
                    env = environment()
                    env.update(
                        QT_QPA_PLATFORM="offscreen",
                        XDG_DATA_HOME=str(scratch / "xdg"),
                        XDG_CONFIG_HOME=str(scratch / "config"),
                    )
                    run(
                        [candidate["python"], "-m", "pytest", "-q"],
                        cwd=candidate["code"],
                        env=env,
                        timeout=300,
                    )
                if not rollback and check(root)["target"] != target:
                    raise UpdateError("main изменилась. Подтвердите новую ревизию заново.")
                if validate(root) != previous["revision"] or schema(database) != original_schema:
                    raise UpdateError("Исходная версия или схема изменились во время подготовки")
                journal.update(phase="launching", candidate=candidate)
                atomic(folder / "transaction.json", journal)
                atomic(folder / "active.json", candidate)
            except Exception as error:
                journal.update(
                    phase="failed",
                    error=str(error)
                    if isinstance(error, UpdateError)
                    else "Ошибка подготовки. Старая версия сохранена.",
                )
                atomic(folder / "active.json", previous)
                atomic(folder / "transaction.json", journal)
                log(folder, journal["error"])
                raise UpdateError(journal["error"]) from error
        try:
            launch(candidate, folder, journal["token"])
        except UpdateError:
            with lease(folder / "gui.lock"), application_lock(database):
                restored = safe_previous(journal, database)
                atomic(folder / "active.json", restored)
                journal.update(phase="failed", error="Неудачный запуск; выбрана предыдущая версия")
                atomic(folder / "transaction.json", journal)
            launch(restored, folder)
            return False
        journal.update(
            phase="rolled_back" if rollback else "complete",
            installed=candidate,
            completed_at=datetime.now(UTC).isoformat(),
        )
        atomic(folder / "transaction.json", journal)
        log(folder, "Возврат завершён" if rollback else "Обновление завершено: " + target)
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=["check", "preflight", "install", "rollback", "revision", "rollback-check"],
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--target")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--wait-fd", type=int)
    args = parser.parse_args()
    try:
        if args.action == "rollback-check":
            with lease(state_dir() / "install.lock"):
                safe_previous(read_json(state_dir() / "transaction.json", {}), args.database)
            value = {"safe": True}
        elif args.action == "check":
            value = check(args.root)
        elif args.action == "revision":
            value = version(args.root)
        elif args.action == "preflight":
            value = preflight(args.root, args.target, args.database, state_dir())
        else:
            if args.wait_fd is None or args.database is None:
                raise UpdateError("Установка запускается только после сохранения и закрытия GUI")
            with os.fdopen(args.wait_fd, "rb") as gate:
                gate.read()  # EOF after process exit, not window.hide().
            try:
                succeeded = install(
                    args.root, args.target, args.database, rollback=args.action == "rollback"
                )
            except (OSError, ValueError, RuntimeError):
                # Pointer recovery is done under the installer lock on the next ordinary launch.
                launch(version(args.root), state_dir())
                raise
            value = {"ok": succeeded}
            if not succeeded:
                print(json.dumps(value))
                return 1
        print(json.dumps(value))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(
            json.dumps(
                {
                    "error": str(error)
                    if isinstance(error, UpdateError)
                    else "Обновление не выполнено. Проверьте сеть, исходную копию и журнал."
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
