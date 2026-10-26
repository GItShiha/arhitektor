import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from arhitektor.infrastructure.database import open_database
from arhitektor.services import Library


@pytest.fixture
def library(tmp_path):
    engine = open_database(tmp_path / "library.sqlite3")
    yield Library(engine)
    engine.dispose()
