"""Real-process regression tests for failed trial launches and lock handoff."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from arhitektor import updater as u
from arhitektor.infrastructure.database import open_database
from arhitektor.services import Library
from arhitektor.update_bootstrap import atomic, read_json


@pytest.fixture
def recovery_release(tmp_path, monkeypatch):
    root = tmp_path / "source"
    shutil.copytree(
        u.ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info")
    )
    (root / ".gitignore").write_text("__pycache__/\n")
    for args in (
        ("init", "-b", "main"),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@example.invalid"),
        ("remote", "add", "origin", min(u.EXPECTED)),
        ("add", "."),
        ("commit", "-m", "previous"),
    ):
        u.git(root, *args)
    old = u.git(root, "rev-parse", "HEAD")
    app = root / "src/arhitektor/app.py"
    app.write_text("raise SystemExit(23)\n" + app.read_text())
    u.git(root, "commit", "-am", "broken trial startup")
    target = u.git(root, "rev-parse", "HEAD")
    u.git(root, "checkout", "--detach", old)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    database = tmp_path / "data/arhitektor/library.sqlite3"
    library = Library(open_database(database))
    library.create("universe", "Сохранённый текст")
    library.engine.dispose()
    folder = database.parent / "updates"
    processes = []

    def release(sha):
        code = tmp_path / sha / "code"
        code.parent.mkdir()
        u.git(root, "worktree", "add", "--detach", code, sha)
        venv = code.parent / "venv"
        u.run([sys.executable, "-m", "venv", "--without-pip", venv])
        site = next((venv / "lib").glob("python*/site-packages"))
        dependency_site = Path(pytest.__file__).resolve().parent.parent
        (site / "release.pth").write_text(
            f"import sys; sys.path.insert(0, {str(code / 'src')!r}); sys.path.append({str(dependency_site)!r})\n"
        )
        return {"code": str(code), "python": str(venv / "bin/python"), "revision": sha}

    previous, candidate = release(old), release(target)
    atomic(folder / "active.json", previous)
    monkeypatch.setattr(u, "version", lambda _: previous)
    monkeypatch.setattr(u, "preflight", lambda *a: None)
    monkeypatch.setattr(u, "check", lambda *a: {"target": target})
    monkeypatch.setattr(u, "prepare", lambda *a: candidate)
    monkeypatch.setattr(u, "probe", lambda *a: None)
    real_run = u.run
    monkeypatch.setattr(
        u, "run", lambda args, **kw: "" if "pytest" in args else real_run(args, **kw)
    )
    try:
        yield root, target, database, folder, previous, candidate, processes
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
        library.engine.dispose()


@pytest.mark.parametrize("failure", ["exit", "executable", "cwd"])
def test_failed_trial_restarts_previous_before_installer_returns(
    recovery_release, monkeypatch, failure
):
    root, target, database, folder, previous, _, processes = recovery_release
    real_launch = u.launch

    def launch(ver, folder, token=None):
        # Wait for a real startup acknowledgement *inside* launch: on the old code,
        # the installer still owns install.lock here and the previous app exits.
        if token and failure == "executable":
            ver = {**ver, "python": str(folder / "missing-python")}
        elif token and failure == "cwd":
            ver = {**ver, "code": str(folder / "missing-code")}
        process = real_launch(ver, folder, token or "restored-health-check")
        processes.append(process)
        return process

    monkeypatch.setattr(u, "launch", launch)
    assert not u.install(root, target, database, folder)
    assert len(processes) == 1 and processes[0].poll() is None
    assert read_json(folder / "active.json") == previous
    assert read_json(folder / "transaction.json")["phase"] == "failed"
    # A second real GUI cannot open this same library.
    with pytest.raises(u.UpdateError):
        u.run([previous["python"], "-m", "arhitektor.app"], cwd=previous["code"], timeout=5)
    processes[0].terminate()
    processes[0].wait(timeout=10)
    library = Library(open_database(database))
    try:
        assert library.catalog()["universe"][0]["title"] == "Сохранённый текст"
    finally:
        library.engine.dispose()


@pytest.mark.parametrize("error_type", [OSError, ValueError, KeyboardInterrupt])
def test_readiness_error_reaps_real_trial_before_recovery(monkeypatch, tmp_path, error_type):
    processes = []
    real_popen = subprocess.Popen

    def start(*args, **kwargs):
        process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(u.subprocess, "Popen", start)

    def broken_read(*args):
        raise error_type("readiness unavailable")

    monkeypatch.setattr(u, "read_json", broken_read)
    with pytest.raises(error_type):
        u.launch({"python": sys.executable, "code": str(tmp_path)}, tmp_path, "trial")
    assert len(processes) == 1 and processes[0].poll() is not None


@pytest.mark.parametrize("phase", ["launching", "failed"])
def test_killed_installer_releases_leases_and_previous_starts(recovery_release, phase):
    root, _, database, folder, previous, candidate, processes = recovery_release
    marker = folder / "installer-locked"
    script = f"""
import signal
from pathlib import Path
from arhitektor import updater as u
root = Path({str(root)!r})
folder = Path({str(folder)!r})
previous = {previous!r}
candidate = {candidate!r}
u.version = lambda _: previous
u.preflight = lambda *a: None
u.check = lambda *a: {{"target": candidate["revision"]}}
u.prepare = lambda *a: candidate
u.probe = lambda *a: None
real_run = u.run
u.run = lambda args, **kw: "" if "pytest" in args else real_run(args, **kw)
real_launch = u.launch
def launch(ver, folder, token=None):
    if (token and {phase!r} == "launching") or (not token and {phase!r} == "failed"):
        Path({str(marker)!r}).touch()
        signal.pause()
    return real_launch(ver, folder, token)
u.launch = launch
u.install(root, candidate["revision"], Path({str(database)!r}), folder)
"""
    holder = subprocess.Popen([sys.executable, "-c", script], cwd=root)
    processes.append(holder)
    deadline = time.monotonic() + 5
    while not marker.exists() and holder.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists(), "Installer did not reach interruption barrier"
    library = Library(open_database(database))
    try:
        library.create("universe", "Новый текст перед отключением")
    finally:
        library.engine.dispose()
    holder.kill()
    holder.wait(timeout=5)
    # There is no timing grace period: kernel release on process exit is sufficient.
    restored = u.launch(previous, folder, "after-interruption")
    processes.append(restored)
    assert restored.poll() is None
    assert read_json(folder / "active.json") == previous
    assert read_json(folder / "transaction.json")["phase"] == "failed"
    restored.terminate()
    restored.wait(timeout=10)
    library = Library(open_database(database))
    try:
        assert len(library.catalog()["universe"]) == 2
    finally:
        library.engine.dispose()


def test_failed_previous_spawn_is_reported_without_second_attempt(recovery_release, monkeypatch):
    root, target, database, folder, previous, _, _ = recovery_release
    calls = []

    def launch(ver, folder, token=None):
        calls.append(token)
        raise FileNotFoundError("missing interpreter")

    monkeypatch.setattr(u, "launch", launch)
    with pytest.raises(u.UpdateError, match="не запущена"):
        u.install(root, target, database, folder)
    assert len(calls) == 2 and calls[1] is None
    assert read_json(folder / "active.json") == previous
    assert "не запущена" in read_json(folder / "transaction.json")["error"]


def test_cli_does_not_blindly_spawn_after_install_exception(monkeypatch, tmp_path):
    import os

    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    monkeypatch.setattr(
        sys,
        "argv",
        ["updater", "install", "--database", str(tmp_path / "db"), "--wait-fd", str(read_fd)],
    )

    def failed(*args, **kwargs):
        raise u.UpdateError("restart already attempted or another installer owns the lease")

    monkeypatch.setattr(u, "install", failed)

    def unexpected(*args):
        pytest.fail("CLI must not initiate an extra uncoordinated restart")

    monkeypatch.setattr(u, "launch", unexpected)
    assert u.main() == 1
