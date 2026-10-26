"""Transactional use cases; no Qt objects or long-lived sessions."""

import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from arhitektor.models import Article, ArticleRelation, Entity, Scene, Universe, Work

MODELS = {"universe": Universe, "article": Article, "work": Work, "scene": Scene}
EDITABLE = {
    "universe": {"title", "description", "settings"},
    "article": {"title", "kind", "content", "tags", "fields"},
    "work": {"title", "kind", "description", "status", "universe_id"},
    "scene": {"title", "content"},
}


def count_words(text: str) -> int:
    return len(re.findall(r"[^\W_]+(?:[-’'][^\W_]+)*", text, re.UNICODE))


def record(obj: Entity) -> dict[str, Any]:
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


class Library:
    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, kind: str, identifier: int) -> dict[str, Any]:
        with Session(self.engine) as session:
            obj = session.get(MODELS[kind], identifier)
            if obj is None:
                raise ValueError("Объект не найден")
            return record(obj)

    def catalog(self) -> dict[str, list[dict[str, Any]]]:
        with Session(self.engine) as session:
            session.connection().exec_driver_sql("BEGIN")
            data = {
                kind: [
                    record(obj)
                    for obj in session.scalars(
                        select(model).order_by(model.position if kind == "scene" else model.id)
                    )
                ]
                for kind, model in MODELS.items()
            }
            data["relation"] = [record(row) for row in session.scalars(select(ArticleRelation))]
            return data

    def search(self, universe_id: int, query: str) -> list[dict[str, Any]]:
        # Unicode casefold also handles Cyrillic, unlike SQLite's built-in NOCASE.
        needle = query.casefold().strip()
        with Session(self.engine) as session:
            articles = session.scalars(select(Article).where(Article.universe_id == universe_id))
            return [
                record(a)
                for a in articles
                if needle in " ".join([a.title, a.content, *a.tags]).casefold()
            ]

    def create(self, kind: str, title: str, parent: int | None = None) -> dict[str, Any]:
        if not title.strip():
            raise ValueError("Введите название")
        with Session(self.engine) as session, session.begin():
            values: dict[str, Any] = {"title": title.strip()}
            if kind in ("article", "work"):
                if kind == "article" and parent is None:
                    raise ValueError("Статья должна принадлежать вселенной")
                values["universe_id"] = parent
            if kind == "scene":
                if parent is None:
                    raise ValueError("Выберите произведение")
                scenes = list(session.scalars(select(Scene).where(Scene.work_id == parent)))
                values.update(work_id=parent, position=len(scenes))
            obj = MODELS[kind](**values)
            session.add(obj)
            session.flush()
            return record(obj)

    def update(self, kind: str, identifier: int, values: dict[str, Any]) -> dict[str, Any]:
        if set(values) - EDITABLE[kind]:
            raise ValueError("Недопустимые поля")
        if "title" in values and not str(values["title"]).strip():
            raise ValueError("Введите название")
        for key in ("fields", "settings"):
            if key in values and not isinstance(values[key], dict):
                raise ValueError("Дополнительные поля должны быть JSON-объектом")
        if "tags" in values and (
            not isinstance(values["tags"], list)
            or not all(isinstance(tag, str) for tag in values["tags"])
        ):
            raise ValueError("Теги должны быть списком строк")
        with Session(self.engine) as session, session.begin():
            obj = session.get(MODELS[kind], identifier)
            if obj is None:
                raise ValueError("Объект не найден")
            for key, value in values.items():
                setattr(obj, key, value)
            if isinstance(obj, Scene):
                obj.word_count = count_words(obj.content)
            session.flush()
            return record(obj)

    @staticmethod
    def _reorder(session: Session, scenes: list[Scene]) -> None:
        # Two phases avoid transient collisions with the UNIQUE constraint.
        for index, scene in enumerate(scenes):
            scene.position = -index - 1
        session.flush()
        for index, scene in enumerate(scenes):
            scene.position = index
        session.flush()

    def move_scene(self, identifier: int, delta: int) -> None:
        if delta not in (-1, 1):
            raise ValueError("Шаг перемещения должен быть -1 или 1")
        with Session(self.engine) as session, session.begin():
            scene = session.get(Scene, identifier)
            if scene is None:
                raise ValueError("Сцена не найдена")
            scenes = list(
                session.scalars(
                    select(Scene).where(Scene.work_id == scene.work_id).order_by(Scene.position)
                )
            )
            index = scenes.index(scene)
            target = index + delta
            if 0 <= target < len(scenes):
                scenes[index], scenes[target] = scenes[target], scenes[index]
                self._reorder(session, scenes)

    def delete(self, kind: str, identifier: int) -> None:
        with Session(self.engine) as session, session.begin():
            obj = session.get(MODELS[kind], identifier)
            if obj is None:
                raise ValueError("Объект не найден")
            work_id = obj.work_id if isinstance(obj, Scene) else None
            session.delete(obj)
            session.flush()
            if work_id is not None:
                scenes = list(
                    session.scalars(
                        select(Scene).where(Scene.work_id == work_id).order_by(Scene.position)
                    )
                )
                self._reorder(session, scenes)

    def backup(self, destination: Path) -> Path:
        source = Path(str(self.engine.url.database))
        if destination.exists() or destination.resolve() == source.resolve():
            raise ValueError("Выберите новое имя для резервной копии")
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Publish a complete, verified online backup atomically, without overwriting files.
        fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".sqlite3.tmp")
        os.close(fd)
        try:
            with (
                closing(sqlite3.connect(source)) as src,
                closing(sqlite3.connect(temporary)) as dst,
            ):
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Проверка резервной копии не пройдена")
            with open(temporary, "rb") as stream:
                os.fsync(stream.fileno())
            os.link(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return destination

    def export(self, destination: Path) -> Path:
        if destination.resolve() == Path(str(self.engine.url.database)).resolve():
            raise ValueError("Нельзя заменить рабочую базу экспортом")
        if destination.exists():
            raise ValueError("Выберите новое имя для экспорта")
        payload = {
            "format": "arhitektor",
            "version": 1,
            "exported_at": datetime.now(UTC).isoformat(),
            "data": self.catalog(),
        }
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    payload,
                    stream,
                    ensure_ascii=False,
                    indent=2,
                    default=lambda value: value.isoformat(),
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, destination)  # Atomic publication, never overwrite existing files.
        finally:
            Path(temporary).unlink(missing_ok=True)
        return destination
