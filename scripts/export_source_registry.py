
import argparse
import json
from datetime import date, datetime
from pathlib import Path  # noqa: F401

import pandas as pd
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import SourceRegistry

EXPORT_FIELDS = [
    "source_key",
    "source_name",
    "authority",
    "market",
    "country_code",
    "region",
    "decision_layer",
    "source_type",
    "access_type",
    "implementation_status",
    "http_method",
    "source_url",
    "companion_url",
    "data_format",
    "authentication",
    "retrieval_strategy",
    "decision_content",
    "update_frequency",
    "coverage_notes",
    "limitations",
    "documentation_url",
    "verification_notes",
    "verified_on",
    "data_as_of",
    "freshness_status",
    "source_status",
    "is_enabled",
    "catalog_sections",
    "last_checked_at",
    "last_successful_sync_at",
    "created_at",
    "updated_at",
]


def serialize_value(value):
    """Convert database values into export-friendly values."""

    if isinstance(value, (date, datetime)):
        return value.isoformat()

    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            ensure_ascii=False,
            default=str,
        )

    return value


def build_registry_rows(records: list[SourceRegistry]) -> list[dict]:
    """Build the main source registry export rows."""

    rows = []

    for record in records:
        row = {}

        for field in EXPORT_FIELDS:
            row[field] = serialize_value(
                getattr(record, field)
            )

        rows.append(row)

    return rows


def build_metadata_rows(
    records: list[SourceRegistry],
) -> list[dict]:
    """Export original workbook-row metadata separately."""

    rows = []

    for record in records:
        metadata = record.source_metadata or {}

        for section, original_data in metadata.items():
            rows.append(
                {
                    "source_key": record.source_key,
                    "source_name": record.source_name,
                    "authority": record.authority,
                    "market": record.market,
                    "catalog_section": section,
                    "original_source_data": json.dumps(
                        original_data,
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export the DreamBigHealth source registry."
    )

    parser.add_argument(
        "--prefix",
        default="source_registry",
        help="Output filename prefix.",
    )

    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    export_dir = settings.export_dir
    export_dir.mkdir(parents=True, exist_ok=True)

    csv_path = export_dir / f"{args.prefix}_{timestamp}.csv"
    excel_path = export_dir / f"{args.prefix}_{timestamp}.xlsx"

    with SessionLocal() as db:
        records = db.scalars(
            select(SourceRegistry).order_by(
                SourceRegistry.market,
                SourceRegistry.authority,
                SourceRegistry.source_name,
            )
        ).all()

        registry_rows = build_registry_rows(records)
        metadata_rows = build_metadata_rows(records)

    registry_df = pd.DataFrame(
        registry_rows,
        columns=EXPORT_FIELDS,
    )

    metadata_df = pd.DataFrame(
        metadata_rows,
        columns=[
            "source_key",
            "source_name",
            "authority",
            "market",
            "catalog_section",
            "original_source_data",
        ],
    )

    registry_df.to_csv(
        csv_path,
        index=False,
        encoding="utf-8-sig",
    )

    with pd.ExcelWriter(
        excel_path,
        engine="openpyxl",
    ) as writer:
        registry_df.to_excel(
            writer,
            sheet_name="Source_Registry",
            index=False,
        )

        metadata_df.to_excel(
            writer,
            sheet_name="Catalog_Metadata",
            index=False,
        )

        notes_df = pd.DataFrame(
            [
                {
                    "Item": "Purpose",
                    "Description": (
                        "Structured global regulatory and HTA source registry."
                    ),
                },
                {
                    "Item": "Part A",
                    "Description": (
                        "Imported from the Code_Ready workbook sheet."
                    ),
                },
                {
                    "Item": "Part B",
                    "Description": (
                        "Imported from the HTA_Market_Access workbook sheet."
                    ),
                },
                {
                    "Item": "Brazil additions",
                    "Description": (
                        "ANVISA registered medicines and the newer "
                        "CONITEC Technologies in demand Excel source."
                    ),
                },
                {
                    "Item": "Historical CONITEC",
                    "Description": (
                        "The older CSV is retained as a historical source "
                        "and marked stale."
                    ),
                },
                {
                    "Item": "Freshness",
                    "Description": (
                        "not_checked means that source freshness has not "
                        "yet been established by a connector sync."
                    ),
                },
                {
                    "Item": "Missing metadata",
                    "Description": (
                        "Blank fields mean the source catalog did not "
                        "provide that information."
                    ),
                },
            ]
        )

        notes_df.to_excel(
            writer,
            sheet_name="Read_Me",
            index=False,
        )

        for sheet_name in (
            "Source_Registry",
            "Catalog_Metadata",
            "Read_Me",
        ):
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions

            for column_cells in worksheet.columns:
                max_length = max(
                    len(str(cell.value or ""))
                    for cell in column_cells
                )

                column_letter = column_cells[0].column_letter

                worksheet.column_dimensions[
                    column_letter
                ].width = min(max(max_length + 2, 14), 55)

    print(f"Exported {len(records)} source records.")
    print(f"CSV:   {csv_path}")
    print(f"Excel: {excel_path}")


if __name__ == "__main__":
    main()
