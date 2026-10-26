"""Exercise the actual startup, migrations, Qt event loop and orderly shutdown."""

import os
import subprocess
import sys


def test_application_entrypoint(tmp_path):
    script = """
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from arhitektor import app
from arhitektor.ui.window import MainWindow

class SmokeApplication(QApplication):
    def __init__(self, args):
        super().__init__(args)
        self.poll = QTimer(self)
        self.poll.setInterval(100)
        self.poll.timeout.connect(self.check)
        self.poll.start()
        self.seen = False

    def check(self):
        for window in self.topLevelWidgets():
            if isinstance(window, MainWindow) and window.catalog:
                self.seen = True
                self.poll.stop()
                window.close()

app.QApplication = SmokeApplication
result = app.main()
assert result == 0
assert QApplication.instance().seen
"""
    process = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "XDG_DATA_HOME": str(tmp_path)},
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert process.returncode == 0, process.stderr
    assert (tmp_path / "arhitektor" / "library.sqlite3").is_file()
    assert not (tmp_path / "arhitektor" / "application.lock").exists()
