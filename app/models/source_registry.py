
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SourceRegistry(Base):
    """
    Stores one canonical registry record per official data source.

    Catalog entries appearing in multiple workbook sheets are merged
    into one record while preserving their original catalog sections.
    """

    __tablename__ = "source_registry"

    __table_args__ = (
        UniqueConstraint("source_key", name="uq_source_registry_source_key"),
        Index("ix_source_registry_market", "market"),
        Index("ix_source_registry_authority", "authority"),
        Index("ix_source_registry_source_type", "source_type"),
        Index("ix_source_registry_freshness", "freshness_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    source_key: Mapped[str] = mapped_column(
        String(180),
        nullable=False,
    )

    source_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    authority: Mapped[str] = mapped_column(
        String(250),
        nullable=False,
    )

    market: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    country_code: Mapped[str | None] = mapped_column(
        String(2),
        nullable=True,
    )

    region: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    decision_layer: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="other",
    )

    access_type: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    implementation_status: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    http_method: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    source_url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    companion_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    data_format: Mapped[str | None] = mapped_column(
        String(150),
        nullable=True,
    )

    authentication: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    retrieval_strategy: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    decision_content: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    update_frequency: Mapped[str | None] = mapped_column(
        String(250),
        nullable=True,
    )

    coverage_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    limitations: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    documentation_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    verification_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    verified_on: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    data_as_of: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    freshness_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="not_checked",
    )

    source_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="active",
    )

    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    catalog_sections: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_successful_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return (
            f"<SourceRegistry("
            f"source_key={self.source_key!r}, "
            f"authority={self.authority!r}, "
            f"market={self.market!r})>"
        )
