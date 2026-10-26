"""Universe-scoped templates; legacy values remain untouched."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "article_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "universe_id",
            sa.Integer(),
            sa.ForeignKey("universes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("navigation_kind", sa.String(100), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("definitions", sa.JSON(), nullable=False),
        sa.UniqueConstraint("universe_id", "title", name="uq_template_title"),
    )
    op.execute(
        "ALTER TABLE articles ADD COLUMN template_id INTEGER REFERENCES article_templates(id)"
    )
    connection = op.get_bind()
    for (uid,) in connection.execute(sa.text("SELECT id FROM universes")):
        names = [
            "Персонаж",
            "Государство",
            "Организация",
            "Локация",
            "Событие",
            "Технология",
            "Предмет",
            "Другое",
        ]
        for (name,) in connection.execute(
            sa.text("SELECT DISTINCT kind FROM articles WHERE universe_id=:u"), {"u": uid}
        ):
            if name not in names:
                names.append(name)
        for position, name in enumerate(names):
            result = connection.execute(
                sa.text(
                    "INSERT INTO article_templates(universe_id,title,position,definitions,navigation_kind) VALUES (:u,:n,:p,:d,:n)"
                ),
                {"u": uid, "n": name, "p": position, "d": json.dumps([])},
            )
            connection.execute(
                sa.text("UPDATE articles SET template_id=:t WHERE universe_id=:u AND kind=:n"),
                {"t": result.lastrowid, "u": uid, "n": name},
            )


def downgrade():
    op.execute("ALTER TABLE articles DROP COLUMN template_id")
    op.drop_table("article_templates")
