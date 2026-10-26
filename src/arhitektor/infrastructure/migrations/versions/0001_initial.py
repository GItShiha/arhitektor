"""Initial local writing workspace."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def common():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "universes",
        *common(),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
    )
    op.create_table(
        "articles",
        *common(),
        sa.Column(
            "universe_id",
            sa.Integer(),
            sa.ForeignKey("universes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("fields", sa.JSON(), nullable=False),
    )
    op.create_index("ix_articles_universe_id", "articles", ["universe_id"])
    op.create_table(
        "works",
        *common(),
        sa.Column("universe_id", sa.Integer(), sa.ForeignKey("universes.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(100), nullable=False),
    )
    op.create_index("ix_works_universe_id", "works", ["universe_id"])
    op.create_table(
        "scenes",
        *common(),
        sa.Column(
            "work_id", sa.Integer(), sa.ForeignKey("works.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("work_id", "position", name="uq_scene_position"),
    )
    op.create_index("ix_scenes_work_id", "scenes", ["work_id"])


def downgrade():
    for table in ("scenes", "works", "articles", "universes"):
        op.drop_table(table)
