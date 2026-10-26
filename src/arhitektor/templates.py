"""Template definitions have stable UUIDs; existing values are never renamed or discarded."""

from copy import deepcopy
from datetime import date
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from arhitektor.models import Article, ArticleTemplate, Universe
from arhitektor.services import record

KINDS = {
    "text": "Короткий текст",
    "long": "Многострочный текст",
    "int": "Целое число",
    "float": "Дробное число",
    "bool": "Да/нет",
    "date": "Дата",
    "choice": "Выбор из списка",
    "reference": "Ссылка на статью",
}
BUILTINS = [
    "Персонаж",
    "Государство",
    "Организация",
    "Локация",
    "Событие",
    "Технология",
    "Предмет",
    "Другое",
]


def validate_value(session, uid, definition, value):
    if value is None:
        return
    kind = definition["kind"]
    valid = False
    if kind in ("text", "long"):
        valid = isinstance(value, str)
    elif kind == "int":
        valid = type(value) is int
    elif kind == "float":
        valid = type(value) in (int, float)
    elif kind == "bool":
        valid = type(value) is bool
    elif kind == "date":
        try:
            valid = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
        except ValueError:
            pass
    elif kind == "choice":
        valid = value in definition.get("options", [])
    elif kind == "reference":
        article = session.get(Article, value) if type(value) is int else None
        valid = article is not None and article.universe_id == uid
    if not valid:
        raise ValueError(
            f"Поле «{definition['name']}»: несовместимое значение или ссылка на другую вселенную"
        )


class Templates:
    def __init__(self, engine):
        self.engine = engine

    def list(self, uid):
        with Session(self.engine) as session:
            return [
                record(t)
                for t in session.scalars(
                    select(ArticleTemplate)
                    .where(ArticleTemplate.universe_id == uid)
                    .order_by(ArticleTemplate.position, ArticleTemplate.id)
                )
            ]

    def create(self, uid, title):
        if not title.strip():
            raise ValueError("Введите название типа")
        with Session(self.engine) as session, session.begin():
            if session.get(Universe, uid) is None:
                raise ValueError("Вселенная не найдена")
            if (
                session.scalar(
                    select(ArticleTemplate.id).where(
                        ArticleTemplate.universe_id == uid, ArticleTemplate.title == title.strip()
                    )
                )
                is not None
            ):
                raise ValueError("Тип с таким названием уже существует в этой вселенной")
            position = len(
                list(
                    session.scalars(
                        select(ArticleTemplate).where(ArticleTemplate.universe_id == uid)
                    )
                )
            )
            obj = ArticleTemplate(
                universe_id=uid, title=title.strip(), position=position, definitions=[]
            )
            session.add(obj)
            session.flush()
            return record(obj)

    def save(self, uid, identifier, title, definitions, position):
        if not title.strip():
            raise ValueError("Введите название типа")
        with Session(self.engine) as session, session.begin():
            template = session.get(ArticleTemplate, identifier)
            if template is None or template.universe_id != uid:
                raise ValueError("Шаблон другой вселенной недоступен")
            if (
                session.scalar(
                    select(ArticleTemplate.id).where(
                        ArticleTemplate.universe_id == uid,
                        ArticleTemplate.title == title.strip(),
                        ArticleTemplate.id != identifier,
                    )
                )
                is not None
            ):
                raise ValueError("Тип с таким названием уже существует в этой вселенной")
            old = {d["id"]: d for d in template.definitions}
            result, seen = [], set()
            for raw in deepcopy(definitions):
                key = raw.get("id") or str(uuid4())
                if key in seen or (raw.get("id") and key not in old):
                    raise ValueError("Недопустимый идентификатор поля")
                seen.add(key)
                if not raw["name"].strip() or raw["kind"] not in KINDS:
                    raise ValueError("Проверьте имя и тип поля")
                raw.update(id=key, active=True)
                if "default" in raw:
                    validate_value(session, uid, raw, raw["default"])
                for article in session.scalars(select(Article).where(Article.universe_id == uid)):
                    if key in article.fields and (
                        key not in old
                        or old[key]["kind"] != raw["kind"]
                        or old[key].get("options") != raw.get("options")
                    ):
                        validate_value(session, uid, raw, article.fields[key])
                result.append(raw)
            result.extend(dict(d, active=False) for key, d in old.items() if key not in seen)
            template.title, template.definitions, template.position = (
                title.strip(),
                result,
                position,
            )
            ordered = list(
                session.scalars(
                    select(ArticleTemplate)
                    .where(ArticleTemplate.universe_id == uid)
                    .order_by(ArticleTemplate.position, ArticleTemplate.id)
                )
            )
            ordered = [item for item in ordered if item.id != identifier]
            ordered.insert(min(max(position, 0), len(ordered)), template)
            for index, item in enumerate(ordered):
                item.position = index
            for article in session.scalars(
                select(Article).where(Article.template_id == identifier)
            ):
                article.kind = template.title
            session.flush()
            return record(template)

    def assign(self, uid, article_id, template_id):
        with Session(self.engine) as session, session.begin():
            article = session.get(Article, article_id)
            template = session.get(ArticleTemplate, template_id)
            if (
                article is None
                or template is None
                or article.universe_id != uid
                or template.universe_id != uid
            ):
                raise ValueError("Статья и шаблон должны принадлежать выбранной вселенной")
            values = deepcopy(article.fields)
            for d in template.definitions:
                if d.get("active", True) and "default" in d and d["id"] not in values:
                    validate_value(session, uid, d, d["default"])
                    values[d["id"]] = deepcopy(d["default"])
            article.fields, article.template_id, article.kind = values, template.id, template.title

    def create_with_fields(self, uid, title, definitions, position=0):
        # An outer transaction ensures invalid definitions cannot leave an empty type behind.
        with self.engine.connect() as connection:
            transaction = connection.begin()
            try:
                service = Templates(connection)
                created = service.create(uid, title)
                result = service.save(uid, created["id"], title, definitions, position)
                transaction.commit()
                return result
            except Exception:
                if transaction.is_active:
                    transaction.rollback()
                raise

    def create_article(self, uid, title, template_id):
        from arhitektor.services import Library

        with self.engine.begin() as connection:
            article = Library(connection).create("article", title, uid)
            Templates(connection).assign(uid, article["id"], template_id)
            return Library(connection).get("article", article["id"])
