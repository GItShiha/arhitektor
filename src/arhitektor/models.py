"""Persistence models. JSON fields are replaced as a whole by the service."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Entity(Base):
    __abstract__ = True
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class Universe(Entity):
    __tablename__ = "universes"
    description: Mapped[str] = mapped_column(Text, default="")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Article(Entity):
    __tablename__ = "articles"
    universe_id: Mapped[int] = mapped_column(
        ForeignKey("universes.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(100), default="Персонаж")
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Work(Entity):
    __tablename__ = "works"
    universe_id: Mapped[int | None] = mapped_column(
        ForeignKey("universes.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(100), default="Роман")
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(100), default="Черновик")


class Scene(Entity):
    __tablename__ = "scenes"
    __table_args__ = (UniqueConstraint("work_id", "position", name="uq_scene_position"),)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int]
    word_count: Mapped[int] = mapped_column(default=0)


class ArticleRelation(Base):
    __tablename__ = "article_relations"
    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "label", name="uq_article_relation"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(200))
    reverse_label: Mapped[str] = mapped_column(String(200))
