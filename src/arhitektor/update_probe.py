"""Subprocess-only library and real Qt window probe, always on a disposable copy."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from arhitektor.infrastructure.database import open_database
from arhitektor.services import Library
from arhitektor.ui.window import MainWindow


def main():
    os.environ["ARHITEKTOR_PROBE"] = "1"
    app = QApplication([])
    engine = open_database(Path(sys.argv[1]))
    library = Library(engine)
    catalog = library.catalog()
    assert all(
        key in catalog for key in ("universe", "article", "template", "relation", "work", "scene")
    )
    window = MainWindow(library)
    window.show()

    def ready():
        if window.catalog and window.isEnabled():
            window.close()
        else:
            QTimer.singleShot(20, ready)

    QTimer.singleShot(20, ready)
    QTimer.singleShot(20000, lambda: app.exit(2))
    result = app.exec()
    window.jobs.shutdown()
    engine.dispose()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
