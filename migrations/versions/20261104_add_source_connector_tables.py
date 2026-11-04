"""Add connector sync, artifact and normalized source record tables."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_connectors"
down_revision = "9493b3dd83db"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_key",
            sa.String(180),
            sa.ForeignKey("source_registry.source_key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(150)),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("etag", sa.String(500)),
        sa.Column("last_modified", sa.String(250)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "source_key",
            "sha256",
            name="uq_source_artifacts_source_checksum",
        ),
    )
    op.create_index(
        "ix_source_artifacts_source_created",
        "source_artifacts",
        ["source_key", "created_at"],
    )

    op.create_table(
        "source_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_key",
            sa.String(180),
            sa.ForeignKey("source_registry.source_key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dataset_key", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("rows_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_valid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rows_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "artifact_id",
            sa.Integer(),
            sa.ForeignKey("source_artifacts.id", ondelete="SET NULL"),
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("run_metadata", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_source_sync_runs_source_started",
        "source_sync_runs",
        ["source_key", "started_at"],
    )
    op.create_index(
        "ix_source_sync_runs_status",
        "source_sync_runs",
        ["status"],
    )

    op.create_table(
        "source_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_key",
            sa.String(180),
            sa.ForeignKey("source_registry.source_key", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dataset_key", sa.String(100), nullable=False),
        sa.Column("record_key", sa.String(64), nullable=False),
        sa.Column("record_date", sa.Date()),
        sa.Column("status", sa.String(250)),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_sync_run_id",
            sa.Integer(),
            sa.ForeignKey("source_sync_runs.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint(
            "dataset_key",
            "record_key",
            name="uq_source_records_dataset_record",
        ),
    )
    op.create_index("ix_source_records_dataset", "source_records", ["dataset_key"])
    op.create_index("ix_source_records_source", "source_records", ["source_key"])
    op.create_index(
        "ix_source_records_record_date",
        "source_records",
        ["record_date"],
    )
    op.create_index("ix_source_records_status", "source_records", ["status"])


def downgrade() -> None:
    op.drop_index("ix_source_records_status", table_name="source_records")
    op.drop_index("ix_source_records_record_date", table_name="source_records")
    op.drop_index("ix_source_records_source", table_name="source_records")
    op.drop_index("ix_source_records_dataset", table_name="source_records")
    op.drop_table("source_records")

    op.drop_index("ix_source_sync_runs_status", table_name="source_sync_runs")
    op.drop_index(
        "ix_source_sync_runs_source_started",
        table_name="source_sync_runs",
    )
    op.drop_table("source_sync_runs")

    op.drop_index(
        "ix_source_artifacts_source_created",
        table_name="source_artifacts",
    )
    op.drop_table("source_artifacts")