"""add collaboration query indexes

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "idx_sample_task_deleted_state",
        "task_sample",
        ["task_id", "deleted_at", "state"],
    )
    op.create_index(
        "idx_sample_task_deleted_id",
        "task_sample",
        ["task_id", "deleted_at", "id"],
    )
    op.create_index(
        "idx_pre_annotation_task_sample_deleted",
        "task_pre_annotation",
        ["task_id", "sample_name", "deleted_at"],
    )


def downgrade():
    op.drop_index(
        "idx_pre_annotation_task_sample_deleted",
        table_name="task_pre_annotation",
    )
    op.drop_index("idx_sample_task_deleted_id", table_name="task_sample")
    op.drop_index("idx_sample_task_deleted_state", table_name="task_sample")
