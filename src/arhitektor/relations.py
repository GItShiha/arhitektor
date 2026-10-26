"""One record represents both directions of a relationship."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from arhitektor.models import Article, ArticleRelation


class Relations:
    def __init__(self, engine):
        self.engine = engine

    def list_for(self, article_id: int) -> list[dict]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(ArticleRelation).where(
                    or_(
                        ArticleRelation.source_id == article_id,
                        ArticleRelation.target_id == article_id,
                    )
                )
            )
            result = []
            for row in rows:
                forward = row.source_id == article_id
                other = session.get(Article, row.target_id if forward else row.source_id)
                result.append(
                    {
                        "id": row.id,
                        "article_id": other.id,
                        "title": other.title,
                        "label": row.label if forward else row.reverse_label,
                    }
                )
            return result

    def create(self, source_id: int, target_id: int, label: str, reverse_label: str) -> int:
        label, reverse_label = label.strip(), reverse_label.strip()
        if not label or not reverse_label:
            raise ValueError("Введите прямое и обратное названия отношения")
        if source_id == target_id:
            raise ValueError("Выберите другую статью")
        with Session(self.engine) as session, session.begin():
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
            source, target = session.get(Article, source_id), session.get(Article, target_id)
            if source is None or target is None:
                raise ValueError("Статья не найдена")
            if source.universe_id != target.universe_id:
                raise ValueError("Связи возможны только внутри одной вселенной")
            rows = session.scalars(
                select(ArticleRelation).where(
                    or_(
                        ArticleRelation.source_id == source_id,
                        ArticleRelation.target_id == source_id,
                    )
                )
            )
            for row in rows:
                if (
                    row.source_id == source_id
                    and row.target_id == target_id
                    and row.label.casefold() == label.casefold()
                ) or (
                    row.target_id == source_id
                    and row.source_id == target_id
                    and row.reverse_label.casefold() == label.casefold()
                ):
                    raise ValueError("Такая связь уже существует")
            row = ArticleRelation(
                source_id=source_id, target_id=target_id, label=label, reverse_label=reverse_label
            )
            session.add(row)
            session.flush()
            return row.id

    def delete(self, identifier: int) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(ArticleRelation, identifier)
            if row is None:
                raise ValueError("Связь не найдена")
            session.delete(row)
