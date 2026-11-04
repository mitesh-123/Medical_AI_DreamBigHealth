from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SourceSyncRun(Base):
    __tablename__ = "source_sync_runs"

    __table_args__ = (
        Index("ix_source_sync_runs_source_started", "source_key", "started_at"),
        Index("ix_source_sync_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    source_key: Mapped[str] = mapped_column(
        String(180),
        ForeignKey("source_registry.source_key", ondelete="RESTRICT"),
        nullable=False,
    )

    dataset_key: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    rows_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    artifact_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )


class SourceArtifact(Base):
    __tablename__ = "source_artifacts"

    __table_args__ = (
        UniqueConstraint(
            "source_key",
            "sha256",
            name="uq_source_artifacts_source_checksum",
        ),
        Index("ix_source_artifacts_source_created", "source_key", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    source_key: Mapped[str] = mapped_column(
        String(180),
        ForeignKey("source_registry.source_key", ondelete="RESTRICT"),
        nullable=False,
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    content_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    etag: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(250), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class SourceRecord(Base):
    __tablename__ = "source_records"

    __table_args__ = (
        UniqueConstraint(
            "dataset_key",
            "record_key",
            name="uq_source_records_dataset_record",
        ),
        Index("ix_source_records_dataset", "dataset_key"),
        Index("ix_source_records_source", "source_key"),
        Index("ix_source_records_record_date", "record_date"),
        Index("ix_source_records_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    source_key: Mapped[str] = mapped_column(
        String(180),
        ForeignKey("source_registry.source_key", ondelete="RESTRICT"),
        nullable=False,
    )

    dataset_key: Mapped[str] = mapped_column(String(100), nullable=False)
    record_key: Mapped[str] = mapped_column(String(64), nullable=False)

    record_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str | None] = mapped_column(String(250), nullable=True)

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_sync_runs.id", ondelete="SET NULL"),
        nullable=True,
    )