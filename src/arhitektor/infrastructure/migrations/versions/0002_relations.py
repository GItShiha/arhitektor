"""Add bidirectional article relations without rewriting existing records."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "article_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("reverse_label", sa.String(200), nullable=False),
        sa.UniqueConstraint("source_id", "target_id", "label", name="uq_article_relation"),
    )
    op.create_index("ix_article_relations_source_id", "article_relations", ["source_id"])
    op.create_index("ix_article_relations_target_id", "article_relations", ["target_id"])


def downgrade():
    op.drop_table("article_relations")
