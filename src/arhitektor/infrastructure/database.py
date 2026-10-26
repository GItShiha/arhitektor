import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine


def data_directory() -> Path:
    root = os.environ.get("XDG_DATA_HOME", "")
    return (Path(root) if Path(root).is_absolute() else Path.home() / ".local/share") / "arhitektor"


def open_database(path: Path) -> Engine:
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite:///" + str(path), connect_args={"timeout": 10})

    @event.listens_for(engine, "connect")
    def configure(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    try:
        if path.exists() and path.stat().st_size:
            with closing(sqlite3.connect(path)) as source:
                tables = {
                    row[0]
                    for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "alembic_version" not in tables:
                    raise RuntimeError(
                        "База не содержит версию схемы. Обновление остановлено; данные не изменены."
                    )
                revisions = source.execute("SELECT version_num FROM alembic_version").fetchall()
                if len(revisions) != 1:
                    raise RuntimeError("Неоднозначная версия схемы; обновление остановлено.")
                scripts = ScriptDirectory.from_config(cfg)
                revision = revisions[0][0]
                scripts.get_revision(revision)  # Reject an unknown schema before any mutation.
                if revision != scripts.get_current_head():
                    backups = path.parent / "backups"
                    backups.mkdir(exist_ok=True)
                    name = datetime.now(UTC).strftime("pre-migration-%Y%m%d-%H%M%S-%f.sqlite3")
                    with closing(sqlite3.connect(backups / name)) as backup:
                        source.backup(backup)
                        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                            raise RuntimeError("Проверка копии перед миграцией не пройдена")
        with engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                cfg.attributes["connection"] = connection
                command.upgrade(cfg, "head")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
    except Exception:
        engine.dispose()
        raise
    return engine
